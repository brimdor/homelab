"""Qualify automatic original startup after loss of a copied recovery controller."""

import hashlib
import os
import re
import signal
import subprocess
import time

import gitea_postgres_account_recovery as recovery


STATE = '/opt/bitnami/postgresql/tmp/maintenance-103'
# Both contenders use the same open file description through native children.
# A normal-start marker permanently refuses later recovery in this Pod lifetime.
STARTUP = '''umask 077
state=/opt/bitnami/postgresql/tmp/maintenance-103
mkdir -- "$state"
exec 9>"$state/lock"
printf '%s\\n' waiting > "$state/phase"
for ((n=0; n<300; n++)); do
    [[ ! -e "$state/claimed" ]] || break
    sleep 0.1
done
flock --exclusive 9
printf '%s\\n' normal > "$state/phase"
exec "$@"
'''

CLAIM = '''umask 077
state=/opt/bitnami/postgresql/tmp/maintenance-103
[[ ! -L "$state" && $(stat -c '%u:%a' "$state") == 1001:700 ]]
[[ -f "$state/lock" && ! -L "$state/lock" && $(stat -c '%h' "$state/lock") == 1 ]]
exec 9>"$state/lock"
flock --exclusive --nonblock 9
[[ $(cat "$state/phase") == waiting && ! -e /bitnami/postgresql/data/postmaster.pid ]]
(set -o noclobber; printf '%s\\n' "$BASHPID" > "$state/claimed")
printf 'HOMELAB103:CLAIMED:%s\\n' "$$"
IFS= read -r request || exit 0
[[ "$request" == run ]]
"$@" <&0 &
child=$!
printf '%s\\n' "$child" > "$state/native-child"
wait "$child"
'''


def wait_for(check, message):
    deadline = time.monotonic() + 65
    while not check():
        if time.monotonic() >= deadline:
            raise RuntimeError(message)
        time.sleep(0.05)


def phase(container):
    response = recovery.execute(container, '/bin/cat', STATE + '/phase', allow_error=True)
    return response.stdout.strip() if not response.returncode else b''


def ordinary(container, credentials, hba):
    pid = os.fork()
    if pid == 0:
        try:
            recovery.normal_start(container, credentials, hba, startup_guard=True)
            os._exit(0)
        except BaseException:
            os._exit(70)
    return pid


def claim(container, failed=False):
    recovery.common.require_no_logging(container)
    argv = ['docker', 'exec', '-i', container, '/bin/bash', '-ceu', CLAIM, 'maintenance-103-controller',
            '/bin/bash', '-ceu', recovery.SINGLE_WRAPPER, 'maintenance-103-single',
            recovery.BIN + 'postgres', '--single', '-D', recovery.DATA,
            *recovery.OPTIONS, *(['-c', 'log_min_messages=error'] if failed else []), 'postgres']
    child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    line = child.stdout.readline()
    match = re.fullmatch(rb'HOMELAB103:CLAIMED:([0-9]+)\n', line)
    if not match:
        child.communicate()
        raise RuntimeError('copied recovery controller failed to acquire startup guard; raw output discarded')
    return child, int(match[1])


def operation(work, volumes, run_id, image_id, credentials, hba):
    with recovery.prepared_copy(work, volumes, run_id, image_id, hba) as container:
        recovery.normal_start(container, credentials, hba)
        original = recovery.dumps(container, credentials['app'], 'gitea')
        recovery.stop(container)
        before = recovery.parse_catalog(recovery.single(container, recovery.catalog_sql().encode()).stdout)
        receipts = []
        last = 'success' if work.name == '0' else 'controller-killed-during-sql'
        for mode in ('controller-absent', 'controller-eof', 'failed-sql', last):
            starter = ordinary(container, credentials, hba)
            controller = None
            reaped = False
            try:
                wait_for(lambda: phase(container) == b'waiting', 'copied startup claim window missing')
                if mode != 'controller-absent':
                    controller, native_pid = claim(container, failed=mode == 'failed-sql')
                    # An unrelated contender must not acquire a claimed recovery window.
                    refused = recovery.execute(container, '/usr/bin/flock', '--exclusive', '--nonblock',
                                               STATE + '/lock', '/bin/true', allow_error=True)
                    if refused.returncode != 1 or phase(container) != b'waiting':
                        raise RuntimeError('copied startup guard did not exclude concurrent startup')
                    if mode == 'controller-eof':
                        output, errors = controller.communicate()
                        if controller.returncode or output or errors:
                            raise RuntimeError('copied EOF controller disposition differs')
                    else:
                        transaction = recovery.role_transaction(credentials['admin'],
                                                                'failed' if mode == 'failed-sql' else 'commit')
                        if mode == 'controller-killed-during-sql':
                            transaction = b"COPY (SELECT 'HOMELAB103:SQL-RUNNING') TO STDOUT;\nSELECT pg_sleep(3);\n" + transaction
                        controller.stdin.write(b'run\n' + transaction)
                        controller.stdin.flush()
                        if mode == 'controller-killed-during-sql':
                            # Observe execution inside PostgreSQL before killing its controller.
                            while True:
                                line = controller.stdout.readline()
                                if not line:
                                    raise RuntimeError('native copied SQL execution witness missing; raw output discarded')
                                if b'HOMELAB103:SQL-RUNNING\n' in line:
                                    break
                            recovery.execute(container, '/bin/kill', '-KILL', str(native_pid))
                            # Actual running native child must retain exclusion after controller death.
                            time.sleep(0.2)
                            refused = recovery.execute(container, '/usr/bin/flock', '--exclusive', '--nonblock',
                                                       STATE + '/lock', '/bin/true', allow_error=True)
                            if refused.returncode != 1 or phase(container) != b'waiting':
                                raise RuntimeError('native offline child lost exclusion after controller SIGKILL')
                        controller.stdin.close()
                        controller.stdin = None
                        output, errors = controller.communicate()
                        raw = output + errors
                        if mode == 'failed-sql':
                            if (controller.returncode or len(re.findall(rb'ERROR:\s+(?:22012:\s+)?division by zero', raw)) != 1 or
                                    re.search(rb'\b(?:FATAL|PANIC):', raw)):
                                raise RuntimeError('guarded copied harmless SQL failure differs; raw output discarded')
                        elif mode == 'controller-killed-during-sql':
                            if controller.returncode != 137 or re.search(rb'\b(?:ERROR|FATAL|PANIC):', raw):
                                raise RuntimeError('guarded copied controller SIGKILL disposition differs; raw output discarded')
                        elif controller.returncode or re.search(rb'\b(?:ERROR|FATAL|PANIC):', raw):
                            raise RuntimeError('guarded copied transaction failed; raw output discarded')
                pid, status = os.waitpid(starter, 0)
                reaped = True
                if pid != starter or not os.WIFEXITED(status) or os.WEXITSTATUS(status):
                    raise RuntimeError('automatic original copied startup failed; raw output discarded')
                if phase(container) != b'normal' or recovery.dumps(container, credentials['app'], 'gitea') != original:
                    raise RuntimeError('automatic copied startup changed complete application data')
                # A live normal postmaster must permanently reject another recovery claim.
                rejected = recovery.execute(container, '/bin/bash', '-ceu', CLAIM, 'maintenance-103-rejected',
                                            '/bin/true', allow_error=True)
                if not rejected.returncode:
                    raise RuntimeError('normal postmaster allowed a late recovery controller')
                if mode == last and recovery.client(container, credentials['admin'], 'postgres', 'psql',
                                                    '-XAtq', '-d', 'postgres', '-c', 'SELECT current_user',
                                                    host='127.0.0.1') != b'postgres\n':
                    raise RuntimeError('guarded copied normal administrator authentication failed')
                recovery.stop(container)
                after = recovery.parse_catalog(recovery.single(container, recovery.catalog_sql().encode()).stdout)
                if mode == last:
                    recovery.require_role_only(before, after, credentials['admin'])
                elif after != before:
                    raise RuntimeError('guarded copied fallback changed authorization')
                receipts.append({'mode': mode, 'automatic_original_startup': True,
                                 'complete_logical_data_equal': True, 'late_claim_refused': True,
                                 'native_child_lock_retained_after_sigkill': mode == 'controller-killed-during-sql',
                                 'transaction_replayed': False})
            finally:
                if controller and controller.poll() is None:
                    controller.communicate()
                if not reaped:
                    os.kill(starter, signal.SIGKILL)
                    os.waitpid(starter, 0)
            recovery.execute(container, '/bin/rm', '-rf', '--', STATE)
        return {'full_dump_sha256': {name: hashlib.sha256(raw).hexdigest() for name, raw in original.items()},
                'startup_guard_attempts': receipts, 'production_mutated': False,
                'production_cold_capture_and_chart_wiring_unqualified': True}
