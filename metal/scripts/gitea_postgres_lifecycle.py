"""Gitea-independent supervisor qualification on exact protected PostgreSQL copies."""

import hashlib
import os
import re
import signal

import gitea_postgres_account_recovery as recovery
from maintenance_actor_hold import exclusive_file, fsync_directory


MODES = ('interrupted-before', 'failed', 'committed-unacknowledged', 'success')


def record(path, value):
    exclusive_file(path, recovery.common.canonical(value), 0o600)


def begin(directory, mode, binding):
    if mode not in MODES or set(binding) != {'image', 'source_manifest_sha256', 'hba_sha256', 'catalog_sha256'}:
        raise RuntimeError('unreviewed copied controller intent')
    if (binding['image'] != recovery.control.IMAGE or binding['source_manifest_sha256'] != recovery.control.CHECKSUM or
            binding['hba_sha256'] != '625018986f8ca9e5f4bff3b1e4ffcdc29d4d96d3cd55ed07f02aa514a30f7e05' or
            not isinstance(binding['catalog_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', binding['catalog_sha256'])):
        raise RuntimeError('copied controller binding differs')
    intent = {'version': 1, 'mode': mode, 'binding': binding}
    # Exclusive creation is the once-only gate, including after uncertain child exit.
    record(directory / (mode + '-intent.json'), intent)
    return hashlib.sha256(recovery.common.canonical(intent)).hexdigest()


def observed_outcome(before, after, password, mode):
    if mode not in MODES:
        raise RuntimeError('unreviewed copied controller outcome')
    if mode in ('interrupted-before', 'failed'):
        if after != before:
            raise RuntimeError('aborted copied controller changed authorization')
        return 'unchanged'
    recovery.require_role_only(before, after, password)
    if after == before:
        raise RuntimeError('committed copied controller did not change the mismatched password')
    return 'committed'


def attempt(directory, mode, binding, container, credentials, before):
    intent_sha256 = begin(directory, mode, binding)
    child = os.fork()
    if child == 0:
        try:
            if mode == 'interrupted-before':
                os.kill(os.getpid(), signal.SIGKILL)
            transaction = 'failed' if mode == 'failed' else 'commit'
            recovery.single(container, recovery.role_transaction(credentials['admin'], transaction),
                            expected_failure=mode == 'failed')
            if mode == 'committed-unacknowledged':
                os.kill(os.getpid(), signal.SIGKILL)
            record(directory / (mode + '-child.json'), {'intent_sha256': intent_sha256, 'native_returned': True})
            os._exit(0)
        except BaseException:
            # Native output and exception details may contain authentication material.
            os._exit(70)
    waited = False
    try:
        waited_pid, status = os.waitpid(child, 0)
        waited = True
        killed = os.WIFSIGNALED(status) and os.WTERMSIG(status) == signal.SIGKILL
        normal = os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0
        if waited_pid != child or (killed if mode in ('interrupted-before', 'committed-unacknowledged') else normal) is not True:
            raise RuntimeError('copied controller child disposition differs; never replay pending intent')
        child_record = directory / (mode + '-child.json')
        if child_record.exists() != normal:
            raise RuntimeError('copied controller acknowledgement disagrees with actual process exit')
        after = recovery.parse_catalog(recovery.single(container, recovery.catalog_sql().encode()).stdout)
        outcome = observed_outcome(before, after, credentials['admin'], mode)
        return {'mode': mode, 'intent_sha256': intent_sha256, 'child_reaped': True,
                'actual_sigkill': killed, 'native_acknowledgement': normal,
                'observed_outcome': outcome, 'transaction_replayed': False}, after
    finally:
        if not waited:
            try:
                os.kill(child, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(child, 0)


def operation(work, volumes, run_id, image_id, credentials, hba):
    with recovery.prepared_copy(work, volumes, run_id, image_id, hba) as container:
        recovery.normal_start(container, credentials, hba)
        original_dump = recovery.dumps(container, credentials['app'], 'gitea')
        recovery.stop(container)
        before = recovery.parse_catalog(recovery.single(container, recovery.catalog_sql().encode()).stdout)
        cold = recovery.cold_capture_restore(work, container, volumes, run_id, image_id, credentials, hba,
                                             original_dump, before, before_recovery=True)
        directory = work / 'lifecycle'
        directory.mkdir(mode=0o700)
        fsync_directory(work)
        binding = {'image': recovery.control.IMAGE, 'source_manifest_sha256': recovery.control.CHECKSUM,
                   'hba_sha256': hashlib.sha256(hba).hexdigest(),
                   'catalog_sha256': hashlib.sha256(recovery.common.canonical(before)).hexdigest()}
        receipts = []
        last = 'committed-unacknowledged' if work.name == '0' else 'success'
        for mode in ('interrupted-before', 'failed', last):
            receipt, after = attempt(directory, mode, binding, container, credentials, before)
            recovery.normal_start(container, credentials, hba)
            if recovery.dumps(container, credentials['app'], 'gitea') != original_dump:
                raise RuntimeError('autonomous copied startup changed complete application data')
            if receipt['observed_outcome'] == 'committed':
                if recovery.client(container, credentials['admin'], 'postgres', 'psql', '-XAtq', '-d', 'postgres',
                                   '-c', 'SELECT current_user', host='127.0.0.1') != b'postgres\n':
                    raise RuntimeError('autonomous normal administrator authentication differs')
                if recovery.dumps(container, credentials['admin'], 'postgres') != original_dump:
                    raise RuntimeError('autonomous copied administrator dump changed complete data')
            recovery.stop(container)
            if recovery.parse_catalog(recovery.single(container, recovery.catalog_sql().encode()).stdout) != after:
                raise RuntimeError('autonomous ordinary startup changed authorization')
            if recovery.execute(container, '/bin/cat', '/tmp/source-hba.conf').stdout != hba:
                raise RuntimeError('autonomous copied lifecycle changed source HBA')
            # Prove an accepted or uncertain intent cannot launch another SQL child.
            try:
                begin(directory, mode, binding)
            except FileExistsError:
                pass
            else:
                raise RuntimeError('copied lifecycle intent permitted replay')
            receipt.update(ordinary_native_fallback_or_startup=True, full_logical_data_equal=True,
                           unchanged_hba=True, normal_application_auth=True,
                           normal_administrator_auth=receipt['observed_outcome'] == 'committed',
                           second_execution_refused=True)
            record(directory / (mode + '-accepted.json'), receipt)
            receipts.append(receipt)
        return {'full_dump_sha256': {name: hashlib.sha256(raw).hexdigest() for name, raw in original_dump.items()},
                'lifecycle_attempts': receipts, 'fresh_pre_recovery_cold_point': cold,
                'gitea_git_and_api_not_required_during_outage': True,
                'only_original_postgres_password_changed': True,
                'all_owned_child_controllers_reaped': True, 'production_mutated': False}
