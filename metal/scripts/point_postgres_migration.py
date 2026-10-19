#!/usr/bin/env python3
"""Deliver qualified protected archives to a repository-defined isolated restore Job."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import shlex
import signal
import shutil
import subprocess
import tempfile
import time

import point_postgres_recovery as recovery


JOB = "postgres-migration-103-20261019-a"


def kube(*args):
    return json.loads(recovery.common.command([os.environ.get("KUBECTL", "kubectl"), *args, "-o=json"]).stdout)


def protected_command(run_id, manifest_hash, file=None):
    code = "import base64,sys,types; "
    for name in ("etcd_recovery", "mariadb_recovery", "point_postgres_recovery"):
        encoded = base64.b64encode(Path(__file__).with_name(name + ".py").read_bytes()).decode()
        code += ("m=types.ModuleType(" + repr(name) + "); sys.modules[" + repr(name) + "]=m; "
                 "exec(base64.b64decode(" + repr(encoded) + "),m.__dict__); ")
    code += """
import hashlib,json
p=m.point_path(sys.argv[1]); expected=sys.argv[2]
m.protected.protected_file(p/'verified.json'); raw=(p/'verified.json').read_bytes()
assert hashlib.sha256(raw).hexdigest()==expected
manifest=json.loads(raw); m.require_manifest(manifest)
assert manifest['source_quiesced'] is True
m.require_original_restore(p,expected)
accepted=[]
for path in p.glob('restore-*.json'):
 m.protected.protected_file(path); r=json.loads(path.read_bytes())
 if r.get('accepted') and r.get('manifest_sha256')==expected and r.get('version')=='18.6' and r.get('image')==m.CANDIDATE:
  assert all(r.get(k) is True for k in ('schema_matches','logical_data_matches','authorization_matches','offline_checksums_valid','clean_shutdown','protected_hashes_unchanged','production_network_unroutable'))
  assert r['cleanup']['scratch_absent'] and r['cleanup']['owned_containers_absent']
  accepted.append(r)
assert accepted
for name,value in manifest['files'].items():
 assert m.protected.file_digest(p/name)==value
if len(sys.argv)==4:
 name=sys.argv[3]; assert name in ('globals.sql','database.dump')
 with (p/name).open('rb') as source:
  for block in iter(lambda:source.read(1048576),b''): sys.stdout.buffer.write(block)
else: print(json.dumps(manifest))
"""
    arguments = ["python3", "-B", "-c", recovery.compressed_program(code), run_id, manifest_hash]
    if file:
        arguments.append(file)
    return [*recovery.common.SSH[:-1], "-o", "ControlMaster=no", recovery.common.SSH[-1], shlex.join(arguments)]


def require_stopped(namespace, job_uid=None):
    if namespace not in recovery.SOURCES:
        raise RuntimeError("unreviewed namespace")
    if kube("get", "namespace", "kube-system")["metadata"]["uid"] != recovery.common.CLUSTER_UID:
        raise RuntimeError("wrong cluster")
    sts = kube("get", "statefulset", namespace + "-postgres", "-n", namespace)
    claim = kube("get", "pvc", namespace + "-postgres-data", "-n", namespace)
    pv = kube("get", "pv", claim["spec"]["volumeName"])
    if ([sts["metadata"]["uid"], claim["metadata"]["uid"], pv["metadata"]["uid"]] !=
            list(recovery.SOURCES[namespace][1:]) or sts["spec"]["replicas"] != 0 or
            sts["status"].get("replicas", 0) != 0 or claim["status"]["phase"] != "Bound" or
            claim["spec"]["storageClassName"] != "standard-rwo" or
            pv["spec"].get("csi", {}).get("driver") != "rook-ceph.rbd.csi.ceph.com" or
            any(o["metadata"].get("deletionTimestamp") for o in (sts, claim, pv))):
        raise RuntimeError("database is not stopped on the reviewed Ceph volume")
    objects = kube("get", "deployment,cronjob,job,pod", "-n", namespace)["items"]
    deployments = [o for o in objects if o["kind"] == "Deployment"]
    if len(deployments) != 1 or deployments[0]["metadata"]["name"] != namespace:
        raise RuntimeError("writer ownership changed")
    for o in objects:
        s, st = o.get("spec", {}), o.get("status", {})
        own_job = o["metadata"]["name"] == JOB and o["metadata"]["uid"] == job_uid
        own_pod = any(r.get("kind") == "Job" and r.get("uid") == job_uid and r.get("controller")
                      for r in o["metadata"].get("ownerReferences", []))
        if ((o["kind"] == "Deployment" and (s.get("replicas") != 0 or st.get("replicas", 0) != 0)) or
                (o["kind"] == "CronJob" and (s.get("suspend") is not True or st.get("active"))) or
                (o["kind"] == "Job" and st.get("active", 0) and not own_job) or
                (o["kind"] == "Pod" and st.get("phase") not in ("Succeeded", "Failed") and not own_pod)):
            raise RuntimeError("an unreviewed writer or volume consumer remains")
    return claim["metadata"]["uid"]


def require_job(namespace, job_uid, manifest, manifest_hash):
    require_stopped(namespace, job_uid)
    job = kube("get", "job", JOB, "-n", namespace)
    if job["metadata"]["uid"] != job_uid or job["status"].get("failed", 0):
        raise RuntimeError("migration Job changed or failed")
    pods = kube("get", "pods", "-n", namespace, "-l", "job-name=" + JOB)["items"]
    if len(pods) != 1:
        raise RuntimeError("migration Job Pod count changed")
    pod = pods[0]
    if not any(r.get("controller") and r.get("uid") == job_uid for r in pod["metadata"].get("ownerReferences", [])):
        raise RuntimeError("migration Pod ownership changed")
    spec = pod["spec"]
    if (spec.get("automountServiceAccountToken") is not False or spec.get("hostNetwork", False) or
            spec.get("hostPID", False) or spec.get("hostIPC", False) or spec["restartPolicy"] != "Never" or
            len(spec["containers"]) != 1 or len(spec.get("initContainers", [])) != 1 or
            spec["containers"][0]["image"] != recovery.CANDIDATE or
            spec["initContainers"][0]["image"] != recovery.IMAGE or
            spec["securityContext"].get("runAsUser") != 999 or spec["securityContext"].get("runAsGroup") != 999):
        raise RuntimeError("migration image or isolation contract changed")
    container = spec["containers"][0]
    security = container["securityContext"]
    if (security.get("allowPrivilegeEscalation") is not False or security.get("readOnlyRootFilesystem") is not True or
            security.get("capabilities") != {"drop": ["ALL"]}):
        raise RuntimeError("migration container security changed")
    init = spec["initContainers"][0]
    if (init.get("command") != ["/bin/bash", "/scripts/migration.sh", "prepare"] or
            init["securityContext"] != security or
            init["volumeMounts"] != [{"name": "data", "mountPath": "/volume"},
                                    {"name": "script", "mountPath": "/scripts", "readOnly": True},
                                    {"name": "tmp", "mountPath": "/tmp"}]):
        raise RuntimeError("original datadir preparation contract changed")
    env = {e["name"]: e.get("value") for e in container["env"]}
    if (env.get("MANIFEST_SHA256") != manifest_hash or
            env.get("ARCHIVE_SHA256") != manifest["files"]["database.dump"]["sha256"] or
            env.get("GLOBALS_SHA256") != manifest["files"]["globals.sql"]["sha256"] or
            env.get("POSTGRES_USER") != namespace.removesuffix("-canary") or
            env.get("MIGRATION_ID") != "20261019-a" or
            env.get("PGDATA") != "/var/lib/postgresql/pg18-maintenance-103-20261019-a"):
        raise RuntimeError("migration archive or principal binding changed")
    mounts = {v["mountPath"]: v for v in container["volumeMounts"]}
    if (set(mounts) != {"/original", "/recovery", "/scripts", "/tmp", env["PGDATA"]} or
            mounts["/original"].get("readOnly") is not True or mounts["/original"].get("subPath") != "pgdata" or
            mounts["/original"]["name"] != "data" or mounts["/recovery"]["name"] != "data" or
            mounts["/recovery"].get("subPath") != "migration-103-20261019-a" or
            mounts[env["PGDATA"]]["name"] != "data" or
            mounts[env["PGDATA"]].get("subPath") != "pg18-maintenance-103-20261019-a"):
        raise RuntimeError("migration mount ownership or read-only original changed")
    volumes = {v["name"]: v for v in spec["volumes"]}
    if (set(volumes) != {"data", "script", "tmp"} or
            volumes["data"] != {"name": "data", "persistentVolumeClaim": {"claimName": namespace + "-postgres-data"}} or
            volumes["tmp"].get("emptyDir") != {"medium": "Memory"} or
            volumes["script"].get("configMap", {}).get("name") != JOB or
            pod["metadata"].get("labels", {}).get("maintenance.eaglepass.io/operation") != JOB or
            container.get("command") != ["/bin/bash", "/scripts/migration.sh", "restore"]):
        raise RuntimeError("migration volume, command or network selector changed")
    config = kube("get", "configmap", JOB, "-n", namespace)
    if config["data"]["migration.sh"].encode() != Path(__file__).with_suffix(".sh").read_bytes():
        raise RuntimeError("published native migration script differs")
    policy = kube("get", "networkpolicy", JOB, "-n", namespace)["spec"]
    if (set(policy["policyTypes"]) != {"Ingress", "Egress"} or policy.get("ingress", []) or policy.get("egress", []) or
            policy["podSelector"] != {"matchLabels": {"maintenance.eaglepass.io/operation": JOB}}):
        raise RuntimeError("restore network policy is not deny-all")
    return pod


def execute(namespace, pod, *args, input=None):
    response = subprocess.run([os.environ.get("KUBECTL", "kubectl"), "exec", "-i", "-n", namespace, pod,
                               "-c", "restore", "--", *args], input=input, capture_output=True)
    if response.returncode or response.stderr:
        # Native detailed logs remain protected on the Ceph operation directory.
        raise RuntimeError("migration native command failed or warned: " + args[0])
    return response.stdout


def compare(namespace, pod, manifest):
    role = namespace.removesuffix("-canary")
    def run(program, *args):
        return execute(namespace, pod, program, "-h", "/tmp", "-U", role, "-d", role, *args)
    schema = run("pg_dump", "--schema-only", "--no-comments")
    if recovery.digest(recovery.normalized_dump(schema)) != manifest["before"]["schema_sha256"]:
        raise RuntimeError("migration schema differs")
    roles = run("psql", "-X", "-Atq", "-v", "ON_ERROR_STOP=1", "-c", recovery.ROLE_SQL).decode().strip()
    if roles != manifest["before"]["roles_sha256"]:
        raise RuntimeError("migration authorization differs")
    archived = execute(namespace, pod, "pg_restore", "--data-only", "--no-comments", "--file=-", "/recovery/database.dump")
    restored = run("pg_dump", "--data-only", "--no-comments")
    diagnostic = recovery.data_diagnostic(archived, restored)
    if not all(diagnostic[k] for k in ("copy_multiset_equal", "session_settings_equal", "sequence_commands_equal")):
        raise RuntimeError("migration complete logical data differs")
    version = run("psql", "-X", "-Atq", "-v", "ON_ERROR_STOP=1", "-c", "SHOW server_version").strip()
    if version != b"18.6":
        raise RuntimeError("migration executable version differs")
    counts = [int(n) for n in execute(namespace, pod, "psql", "-h", "/tmp", "-U", role, "-d", role,
                                     "-X", "-Atq", "-v", "ON_ERROR_STOP=1", input=recovery.ROW_SQL.encode()).splitlines()]
    if len(counts) != manifest["before"]["features"]["user_tables"] or sum(counts) != diagnostic["archived_rows"]:
        raise RuntimeError("migration relation or row counts differ")
    return {"schema_matches": True, "authorization_matches": True, "logical_data_matches": True,
            "relations": len(counts), "rows": sum(counts), "diagnostic": diagnostic}


def migrate(namespace, job_uid, run_id, manifest_hash):
    manifest = json.loads(recovery.common.command(protected_command(run_id, manifest_hash)).stdout)
    if manifest["namespace"] != namespace:
        raise RuntimeError("protected namespace mismatch")
    pod = require_job(namespace, job_uid, manifest, manifest_hash)
    name, uid = pod["metadata"]["name"], pod["metadata"]["uid"]
    for file in ("globals.sql", "database.dump"):
        require_job(namespace, job_uid, manifest, manifest_hash)
        producer = receiver = None
        try:
            producer = subprocess.Popen(protected_command(run_id, manifest_hash, file), stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
            receiver = subprocess.Popen([os.environ.get("KUBECTL", "kubectl"), "exec", "-i", "-n", namespace,
                name, "-c", "restore", "--", "/bin/bash", "/scripts/migration.sh", "receive", file],
                stdin=producer.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            producer.stdout.close()
            output, errors = receiver.communicate()
            _, upstream_errors = producer.communicate()
            if receiver.returncode or producer.returncode or output or errors or upstream_errors:
                raise RuntimeError("protected archive delivery failed; partial retained, no automatic retry")
        finally:
            for process in (receiver, producer):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    execute(namespace, name, "/bin/bash", "/scripts/migration.sh", "seal")
    while True:
        current = require_job(namespace, job_uid, manifest, manifest_hash)
        if current["metadata"]["uid"] != uid:
            raise RuntimeError("migration Pod replaced")
        state = execute(namespace, name, "cat", "/recovery/state").strip()
        if state == b"awaiting-verification":
            break
        if state != b"sealed":
            raise RuntimeError("unexpected restore state")
        time.sleep(3)
    result = compare(namespace, name, manifest)
    require_job(namespace, job_uid, manifest, manifest_hash)
    execute(namespace, name, "/bin/bash", "/scripts/migration.sh", "accept", manifest_hash)
    while True:
        job = kube("get", "job", JOB, "-n", namespace)
        if job["metadata"]["uid"] != job_uid or job["status"].get("failed", 0):
            raise RuntimeError("migration Job failed after acceptance; preserve original datadir")
        if any(c.get("type") == "Complete" and c.get("status") == "True" for c in job["status"].get("conditions", [])):
            break
        time.sleep(3)
    result.update(accepted=True, namespace=namespace, manifest_sha256=manifest_hash, job_uid=job_uid, pod_uid=uid,
                  original_datadir_preserved=True, offline_checksums_valid=True, clean_shutdown=True)
    return result


def rehearse(native):
    """Exercise the native job lifecycle with synthetic data and no production routes."""
    recovery.common.require_host("pikachu")
    recovery.common.private_root()
    label = "io.eaglepass.point-postgres-migration-rehearsal"
    if recovery.common.docker("ps", "-aq", "--filter=label=" + label).stdout.strip():
        raise RuntimeError("an owned native rehearsal is already active")
    before_images = set(recovery.common.docker("image", "ls", "-q", "--no-trunc").stdout.decode().split())
    root = Path(tempfile.mkdtemp(prefix="point-native-rehearsal-", dir=recovery.common.ROOT))
    containers, images = [], set()
    result = {"accepted": False}
    stage = "create-original"
    try:
        (root / "volume").mkdir(mode=0o700)
        os.chown(root / "volume", 999, 999)
        (root / "migration.sh").write_bytes(native)
        (root / "migration.sh").chmod(0o555)
        os.chmod(root, 0o755)
        def create(image, mounts, environment=()):
            recovery.common.docker("pull", image)
            info = json.loads(recovery.common.docker("image", "inspect", image).stdout)[0]
            image_volume = recovery.require_image(info, image)
            images.add(info["Id"])
            arguments = ["create", "--network=none", "--read-only", "--cap-drop=ALL", "--user=999:999",
                         "--security-opt=no-new-privileges:true", "--ipc=private", "--pids-limit=128", "--cpus=1",
                         "--memory=1g", "--label=" + label + "=103", "--tmpfs=/tmp:rw,nosuid,nodev"]
            arguments += ["--tmpfs=" + image_volume + ":rw,nosuid,nodev,uid=999,gid=999"]
            for source, target, readonly in mounts:
                arguments += ["--mount=type=bind,source=" + str(source) + ",target=" + target + (",readonly" if readonly else "")]
            for key, value in environment:
                arguments += ["--env=" + key + "=" + value]
            identity = recovery.common.docker(*arguments, "--entrypoint=/bin/sh", image,
                                               "-c", "exec sleep 2147483647").stdout.decode().strip()
            containers.append(identity)
            recovery.common.docker("start", identity)
            state = recovery.common.inspect(identity)
            if state["HostConfig"]["NetworkMode"] != "none" or not state["HostConfig"]["ReadonlyRootfs"]:
                raise RuntimeError("native rehearsal isolation changed")
            net = ["nsenter", "--target", str(state["State"]["Pid"]), "--net", "--"]
            links = json.loads(recovery.common.command([*net, "ip", "-j", "address"]).stdout)
            routes = sum((json.loads(recovery.common.command([*net, "ip", f, "-j", "route", "show", "table", "all"]).stdout)
                          for f in ("-4", "-6")), [])
            recovery.common.require_network(links, routes)
            if recovery.common.command([*net, "ip", "route", "get", "10.0.20.50"], check=False).returncode == 0:
                raise RuntimeError("native rehearsal can route to production")
            return identity
        def run(identity, *args, input=None):
            p = subprocess.run(["docker", "exec", "-i", identity, *args], input=input, capture_output=True)
            if p.returncode or p.stderr:
                # Only synthetic values exist in this scratch, but keep diagnostics private and bounded.
                raise RuntimeError("native rehearsal command failed: " + args[0] + ":" + str(p.returncode))
            return p.stdout
        base_env = [("POSTGRES_USER", "pointguide"), ("MIGRATION_ID", "20261019-a"),
                    ("POSTGRES_PASSWORD", "synthetic-rehearsal-only"), ("POSTGRES_INITDB_ARGS", "")]
        original = create(recovery.IMAGE, [(root / "volume", "/volume", False),
                           (root / "migration.sh", "/scripts/migration.sh", True)], base_env)
        stage = "initialize-original-uid999"
        # Native tools may emit successful progress on stderr; shell redirects keep it in owned scratch.
        run(original, "bash", "-ec", "source /usr/local/bin/docker-entrypoint.sh; export PGDATA=/volume/pgdata; docker_init_database_dir --auth-local=trust --auth-host=reject --encoding=UTF8 --locale=en_US.utf8 --data-checksums >/volume/init.log 2>&1; pg_ctl -D /volume/pgdata -l /volume/server.log -o \"-c listen_addresses='' -c unix_socket_directories=/tmp -c unix_socket_permissions=0700\" -w start >/volume/start.log 2>&1")
        stage = "populate-original"
        run(original, "createdb", "-h", "/tmp", "-U", "pointguide", "pointguide")
        run(original, "psql", "-X", "-h", "/tmp", "-U", "pointguide", "-d", "pointguide", "-v", "ON_ERROR_STOP=1",
            input=b"CREATE TABLE public.proof (id integer, value text); INSERT INTO public.proof VALUES (1,'duplicate'),(1,'duplicate'),(2,NULL); CREATE SEQUENCE public.proof_sequence START 9; SELECT nextval('public.proof_sequence');")
        schema = run(original, "pg_dump", "-h", "/tmp", "-U", "pointguide", "-d", "pointguide", "--schema-only", "--no-comments")
        roles = run(original, "psql", "-XAtq", "-h", "/tmp", "-U", "pointguide", "-d", "pointguide", "-v", "ON_ERROR_STOP=1", "-c", recovery.ROLE_SQL)
        globals_sql = run(original, "pg_dumpall", "-h", "/tmp", "-U", "pointguide", "--globals-only", "--no-role-passwords", "--no-tablespaces")
        archive = run(original, "pg_dump", "-h", "/tmp", "-U", "pointguide", "-d", "pointguide", "--format=custom", "--create")
        archived_data = run(original, "pg_dump", "-h", "/tmp", "-U", "pointguide", "-d", "pointguide", "--data-only", "--no-comments")
        run(original, "sh", "-ceu", "pg_ctl -D /volume/pgdata -w -m fast stop >/volume/stop.log 2>&1")
        stage = "prepare-original"
        run(original, "sh", "/scripts/migration.sh", "prepare")
        directory = "pg18-maintenance-103-20261019-a"
        operation = root / "volume/migration-103-20261019-a"
        env = base_env + [("PGDATA", "/var/lib/postgresql/" + directory), ("POSTGRES_PASSWORD", "synthetic-rehearsal-only"),
                          ("MANIFEST_SHA256", "a" * 64), ("GLOBALS_SHA256", recovery.digest(globals_sql)),
                          ("ARCHIVE_SHA256", recovery.digest(archive))]
        candidate = create(recovery.CANDIDATE, [(root / "volume/pgdata", "/original", True),
            (operation, "/recovery", False), (root / "volume" / directory, "/var/lib/postgresql/" + directory, False),
            (root / "migration.sh", "/scripts/migration.sh", True)], env)
        stage = "restore-candidate"
        recovery.common.docker("exec", "--detach", candidate, "/bin/sh", "-c",
                               "/bin/bash /scripts/migration.sh restore >/recovery/native.log 2>&1; printf '%s' $? >/recovery/native.exit")
        for name, data in (("globals.sql", globals_sql), ("database.dump", archive)):
            run(candidate, "/bin/bash", "/scripts/migration.sh", "receive", name, input=data)
        run(candidate, "/bin/bash", "/scripts/migration.sh", "seal")
        while (operation / "state").read_text().strip() == "sealed":
            if (operation / "native.exit").exists():
                raise RuntimeError("native restore stopped before verification")
            time.sleep(1)
        if (operation / "state").read_text().strip() != "awaiting-verification":
            raise RuntimeError("unexpected native rehearsal state")
        stage = "compare-candidate"
        def sql_or_dump(program, *args):
            return run(candidate, program, "-h", "/tmp", "-U", "pointguide", "-d", "pointguide", *args)
        if recovery.normalized_dump(schema) != recovery.normalized_dump(sql_or_dump("pg_dump", "--schema-only", "--no-comments")):
            raise RuntimeError("native rehearsal schema changed")
        if roles != sql_or_dump("psql", "-XAtq", "-v", "ON_ERROR_STOP=1", "-c", recovery.ROLE_SQL):
            raise RuntimeError("native rehearsal role attributes changed")
        comparison = recovery.data_diagnostic(archived_data, sql_or_dump("pg_dump", "--data-only", "--no-comments"))
        if not all(comparison[k] for k in ("copy_multiset_equal", "session_settings_equal", "sequence_commands_equal")):
            raise RuntimeError("native rehearsal duplicate, null or sequence changed")
        run(candidate, "/bin/bash", "/scripts/migration.sh", "accept", "a" * 64)
        while not (operation / "native.exit").exists():
            time.sleep(1)
        if (operation / "native.exit").read_text() != "0" or (operation / "state").read_text().strip() != "complete":
            raise RuntimeError("native rehearsal final checksum or original-preservation gate failed")
        result.update(accepted=True, duplicate_and_null_records_match=True, schema_and_roles_match=True,
                      sequence_matches=True, original_datadir_unchanged=True, offline_checksums_valid=True,
                      clean_shutdown=True, production_network_unroutable=True)
    except Exception as error:
        result.update(error=str(error), stage=stage)
        # This dedicated rehearsal contains only the three hard-coded synthetic records above.
        result["synthetic_diagnostics"] = {str(path.relative_to(root)): path.read_text(errors="replace")[-1500:]
                                           for path in root.rglob("*.log") if path.is_file()}
    finally:
        for identity in reversed(containers):
            recovery.common.docker("rm", "-f", identity)
        shutil.rmtree(root)
        for image in images - before_images:
            if recovery.common.docker("ps", "-aq", "--filter=ancestor=" + image).stdout.strip():
                raise RuntimeError("new rehearsal image acquired another consumer; retained")
            recovery.common.docker("image", "rm", image)
        result["cleanup"] = {"scratch_absent": not root.exists(),
                             "owned_containers_absent": not recovery.common.docker("ps", "-aq", "--filter=label=" + label).stdout.strip()}
    return result


def main():
    def interrupted(_number, _frame):
        raise InterruptedError("migration delivery interrupted; original datadir retained")
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", choices=sorted(recovery.SOURCES), required=True)
    parser.add_argument("--job-uid", required=True)
    parser.add_argument("--run-id", type=recovery.common.run_identifier, required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{64}", args.manifest) or not re.fullmatch(r"[a-f0-9-]{36}", args.job_uid):
        parser.error("exact manifest and Job UID required")
    print(json.dumps(migrate(args.namespace, args.job_uid, args.run_id, args.manifest)), flush=True)


if __name__ == "__main__":
    main()
