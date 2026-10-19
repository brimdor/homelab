#!/usr/bin/env python3
"""Protect and restore the four reviewed Point application PostgreSQL databases."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

import etcd_recovery as common
import mariadb_recovery as protected


IMAGE = "docker.io/library/postgres@sha256:7456ef82e5f5bc43d997f4781bbd7c0d6389bff397564649a356e206ba473aee"
CANDIDATE = "docker.io/library/postgres@sha256:d8703cd7fba306b9fec9268ecedfa8a966846c053036a60e3635791957eb2f66"
LABEL = "io.eaglepass.point-postgres-recovery"
ADMIN = "homelab_restore_admin_20261019"
CONTROL = "homelab_restore_control_20261019"
SOURCES = {
    "pointguide-canary": ("ba24de8b-bcca-4d52-83d2-e61331806c4e", "64ca3e3c-4d93-4f4b-ab70-5f210b0340be",
                          "1078041f-b823-46c8-ab73-26c0c7681bbc", "c55e7b9f-d310-4706-b244-bd249fb82590"),
    "pointview-canary": ("6928f151-9d81-4cc3-896c-c33502319ce2", "642cc4e0-e49a-476a-b538-d3b4d192ab54",
                         "293935d9-b88d-407f-a42e-cf18c605bec8", "80b994ce-ebd9-478c-b911-03549d314ad3"),
    "pointguide": ("9f6eb312-65dd-4244-907f-8b59b1a50d71", "cc3e33f3-a2ca-493d-b42d-ad0a120d546b",
                   "0d9f4dcd-2c5b-4d85-8b1b-5fa0af7c585c", "768823d6-cb15-4e59-80ec-b22d1f1b2bbd"),
    "pointview": ("0c8f639f-f80e-4cdd-9564-d0bd8c705342", "223aa8e1-f141-443b-bdd6-9001eda5acc6",
                  "dfd8cd7c-9cbd-43ee-a7e7-9dc476b61d0a", "614ae0ee-4dd5-4cc2-a6cc-d0592ac0bfd7"),
}
EMPTY_SQL = """SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' AND c.relkind IN ('r','m','p','f');
SELECT count(*) FROM pg_largeobject;"""
FEATURE_SQL = """SELECT json_build_object('version',current_setting('server_version'),
'database',current_database(),'role',current_user,'encoding',current_setting('server_encoding'),
'locale',(SELECT json_build_array(datcollate,datctype,datlocprovider) FROM pg_database WHERE datname=current_database()),
'user_tables',(SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' AND c.relkind IN ('r','m')),'foreign_tables',(SELECT count(*) FROM pg_foreign_table),'large_objects',(SELECT count(*) FROM pg_largeobject),
'extensions',(SELECT json_agg(extname ORDER BY extname) FROM pg_extension),
'custom_tablespaces',(SELECT count(*) FROM pg_tablespace WHERE spcname NOT IN ('pg_default','pg_global')),
'databases',(SELECT json_agg(datname ORDER BY datname) FROM pg_database WHERE NOT datistemplate),
'roles',(SELECT json_agg(rolname ORDER BY rolname) FROM pg_roles WHERE rolname NOT LIKE 'pg_%'),
'prepared_transactions',(SELECT count(*) FROM pg_prepared_xacts),
'subscriptions',(SELECT count(*) FROM pg_subscription),'replication_slots',(SELECT count(*) FROM pg_replication_slots));"""
ROLE_SQL = """WITH roles AS (
SELECT jsonb_agg(jsonb_build_array(rolname,rolsuper,rolinherit,rolcreaterole,rolcreatedb,
rolcanlogin,rolreplication,rolconnlimit,rolvaliduntil::text,rolbypassrls,rolconfig) ORDER BY rolname) AS v
FROM pg_roles WHERE rolname NOT LIKE 'pg_%' AND rolname<>'homelab_restore_admin_20261019'
), members AS (
SELECT jsonb_agg(jsonb_build_array(r.rolname,m.rolname,g.rolname,a.admin_option,a.inherit_option,a.set_option)
ORDER BY r.rolname,m.rolname,g.rolname) AS v FROM pg_auth_members a
JOIN pg_roles r ON r.oid=a.roleid JOIN pg_roles m ON m.oid=a.member JOIN pg_roles g ON g.oid=a.grantor
WHERE r.rolname<>'homelab_restore_admin_20261019' AND m.rolname<>'homelab_restore_admin_20261019'
AND NOT (r.rolname LIKE 'pg_%' AND m.rolname LIKE 'pg_%')
), parameters AS (SELECT jsonb_agg(jsonb_build_array(parname,paracl::text) ORDER BY parname) AS v FROM pg_parameter_acl)
SELECT encode(sha256(convert_to(jsonb_build_array(roles.v,members.v,parameters.v)::text,'UTF8')),'hex')
FROM roles,members,parameters;"""
ROW_SQL = r"""SELECT format('SELECT count(*) FROM ONLY %I.%I',n.nspname,c.relname)
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname<>'information_schema' AND c.relkind IN ('r','m')
ORDER BY n.nspname,c.relname
\gexec
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def error_class(data):
    patterns = {
        "database_exists": rb'database "[^"\n]+" already exists',
        "schema_exists": rb'schema "[^"\n]+" already exists',
        "missing_role": rb'role "[^"\n]+" does not exist',
        "invalid_locale": rb'invalid locale name',
        "permission_denied": rb'permission denied',
        "unsupported_archive": rb'unsupported version .* in file header',
        "missing_extension": rb'(?:could not open extension control file|extension "[^"\n]+" is not available)',
        "unknown_setting": rb'unrecognized configuration parameter',
        "read_only_transaction": rb'cannot execute [^\n]+ in a read-only transaction',
        "duplicate_key": rb'duplicate key value violates unique constraint',
        "missing_type": rb'type "[^"\n]+" does not exist',
        "missing_relation": rb'relation "[^"\n]+" does not exist',
        "connection_failed": rb'connection to server .* failed',
        "file_access": rb'(?:could not open input file|could not read from input file)',
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, data)] or ["unclassified"]


def normalized_dump(data):
    # COPY records may look like comments or psql commands; never normalize them.
    result = []
    copying = False
    for line in data.splitlines(keepends=True):
        if not copying and (re.fullmatch(rb"\\(?:un)?restrict [A-Za-z0-9]+\n", line) or
                            re.fullmatch(rb"-- Dumped (?:from database|by pg_dump) version [^\n]+\n", line)):
            continue
        result.append(line)
        if copying:
            copying = line.rstrip(b"\r\n") != b"\\."
        elif line.startswith(b"COPY ") and line.rstrip(b"\r\n").endswith(b" FROM stdin;"):
            copying = True
    if copying:
        raise RuntimeError("incomplete logical COPY stream")
    return b"".join(result)


def data_sections(data):
    """Describe exact COPY record multisets and all executable data-only SQL."""
    tables, settings, sequences = {}, [], []
    header = None
    rows = []
    for line in normalized_dump(data).splitlines(keepends=True):
        if header is not None:
            if line.rstrip(b"\r\n") == b"\\.":
                key = digest(header)
                if key in tables:
                    raise RuntimeError("duplicate COPY section in data comparison")
                framed = lambda values: b"".join(len(row).to_bytes(8, "big") + row for row in values)
                tables[key] = {"rows": len(rows), "ordered_sha256": digest(framed(rows)),
                               "multiset_sha256": digest(framed(sorted(rows)))}
                header, rows = None, []
            else:
                rows.append(line)
        elif line.startswith(b"COPY ") and line.rstrip(b"\r\n").endswith(b" FROM stdin;"):
            header = line
        elif not line.strip() or line.startswith(b"--"):
            continue
        elif line.startswith(b"SET ") or line.startswith(b"SELECT pg_catalog.set_config("):
            settings.append(digest(line))
        elif line.startswith(b"SELECT pg_catalog.setval("):
            sequences.append(digest(line))
        else:
            raise RuntimeError("unknown executable data-only SQL in comparison")
    if header is not None:
        raise RuntimeError("incomplete COPY section in data comparison")
    return {"tables": tables, "settings": settings, "sequences": sorted(sequences)}


def data_diagnostic(archived, restored):
    original, current = data_sections(archived), data_sections(restored)
    def unordered(value):
        return {key: {k: v for k, v in table.items() if k != "ordered_sha256"}
                for key, table in value["tables"].items()}
    return {"tables": len(original["tables"]), "archived_rows": sum(t["rows"] for t in original["tables"].values()),
            "restored_rows": sum(t["rows"] for t in current["tables"].values()),
            "copy_ordered_equal": original["tables"] == current["tables"],
            "copy_multiset_equal": unordered(original) == unordered(current),
            "session_settings_equal": original["settings"] == current["settings"],
            "sequence_commands_equal": original["sequences"] == current["sequences"],
            "archive_sha256": digest(normalized_dump(archived)),
            "restored_sha256": digest(normalized_dump(restored))}


def remote(mode, run_id, *extra):
    code = "import base64,sys,types; "
    for name in ("etcd_recovery", "mariadb_recovery"):
        encoded = base64.b64encode(Path(__file__).with_name(name + ".py").read_bytes()).decode()
        code += ("m=types.ModuleType(" + repr(name) + "); sys.modules[" + repr(name) +
                 "]=m; exec(base64.b64decode(" + repr(encoded) + "),m.__dict__); ")
    code += "exec(base64.b64decode(" + repr(base64.b64encode(Path(__file__).read_bytes()).decode()) + "))"
    return [*common.SSH[:-1], "-o", "ControlMaster=no", common.SSH[-1],
            shlex.join(["python3", "-B", "-c", code, mode, "--run-id", run_id, *extra])]


def point_path(run_id):
    common.require_host("pikachu")
    common.private_root()
    path = common.ROOT / ("point-postgres-" + common.run_identifier(run_id))
    if path.is_symlink():
        raise RuntimeError("recovery point is a symlink")
    return path


def receive(run_id, name):
    point = point_path(run_id)
    if name == "globals.sql":
        point.mkdir(mode=0o700)
    metadata = point.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise RuntimeError("recovery point is not protected")
    with (point / name).open("xb") as output:
        os.fchmod(output.fileno(), 0o600)
        for block in iter(lambda: sys.stdin.buffer.read(1048576), b""):
            if shutil.disk_usage(point).free < len(block):
                raise RuntimeError("recovery destination is full; protected partial retained")
            output.write(block)
        output.flush()
        os.fsync(output.fileno())
    value = protected.file_digest(point / name)
    if not value["bytes"]:
        raise RuntimeError("empty recovery file; protected partial retained")
    return value


def source_client(namespace, *arguments, database=None):
    role = namespace.removesuffix("-canary")
    command = ['PGPASSWORD="$POSTGRES_PASSWORD"',
               'PGOPTIONS="-c default_transaction_read_only=on -c lock_timeout=10s -c timezone=UTC"',
               "exec", shlex.join(arguments)]
    if database:
        command[0:0] = ["PGDATABASE=" + shlex.quote(database)]
    return [os.environ.get("KUBECTL", "kubectl"), "exec", "-i", "-n", namespace,
            namespace + "-postgres-0", "-c", "main", "--", "sh", "-ceu",
            " ".join(command) + " -h 127.0.0.1 -U " + role]


def source_metadata(namespace):
    role = namespace.removesuffix("-canary")
    def sql(query, database=role):
        return common.command(source_client(namespace, "psql", "-X", "-Atq", "-v", "ON_ERROR_STOP=1",
                                            "-c", query, database=database)).stdout
    features = json.loads(sql(FEATURE_SQL))
    expected_extensions = ["citext", "plpgsql"] if role == "pointview" else ["plpgsql"]
    if (features.get("version") != "17.11" or features.get("database") != role or features.get("role") != role or
            features.get("encoding") != "UTF8" or features.get("locale") != ["en_US.utf8", "en_US.utf8", "c"] or
            features.get("databases") != [role, "postgres"] or features.get("roles") != [role] or
            features.get("extensions") != expected_extensions or any(features.get(k) != 0 for k in
            ("foreign_tables", "large_objects", "custom_tablespaces", "prepared_transactions", "subscriptions", "replication_slots"))):
        raise RuntimeError("reviewed PostgreSQL database features changed")
    for database in ("postgres", "template1"):
        if sql(EMPTY_SQL, database).splitlines() != [b"0", b"0"]:
            raise RuntimeError("another database contains unprotected application data")
    schema = common.command(source_client(namespace, "pg_dump", "--schema-only", "--no-comments", database=role)).stdout
    return {"features": features, "schema_sha256": digest(normalized_dump(schema)),
            "roles_sha256": sql(ROLE_SQL).decode().strip()}


def source_identity(namespace):
    if namespace not in SOURCES:
        raise RuntimeError("unreviewed source namespace")
    client = [os.environ.get("KUBECTL", "kubectl")]
    def get(*args):
        return json.loads(common.command([*client, "get", *args, "-o=json"]).stdout)
    if get("namespace", "kube-system")["metadata"]["uid"] != common.CLUSTER_UID:
        raise RuntimeError("wrong source cluster")
    pod = get("pod", namespace + "-postgres-0", "-n", namespace)
    container = pod["spec"]["containers"]
    statuses = pod["status"].get("containerStatuses", [])
    if (len(container) != 1 or len(statuses) != 1 or container[0]["name"] != "main" or
            not statuses[0]["ready"] or statuses[0]["restartCount"] != 0 or statuses[0]["imageID"] != IMAGE or
            pod["metadata"].get("deletionTimestamp")):
        raise RuntimeError("reviewed ready source image or Pod changed")
    mounts = [m for m in container[0]["volumeMounts"] if m["mountPath"] == "/var/lib/postgresql/data"]
    if len(mounts) != 1:
        raise RuntimeError("source database mount changed")
    volume = next(v for v in pod["spec"]["volumes"] if v["name"] == mounts[0]["name"])
    claim = get("pvc", volume["persistentVolumeClaim"]["claimName"], "-n", namespace)
    pv = get("pv", claim["spec"]["volumeName"])
    owners = [o for o in pod["metadata"]["ownerReferences"] if o.get("controller") and o["kind"] == "StatefulSet"]
    identity = (pod["metadata"]["uid"], owners[0]["uid"] if len(owners) == 1 else None,
                claim["metadata"]["uid"], pv["metadata"]["uid"])
    if (identity != SOURCES[namespace] or claim["status"]["phase"] != "Bound" or
            claim["spec"]["storageClassName"] != "standard-rwo" or
            pv["spec"].get("csi", {}).get("driver") != "rook-ceph.rbd.csi.ceph.com" or
            claim["metadata"].get("deletionTimestamp") or pv["metadata"].get("deletionTimestamp")):
        raise RuntimeError("reviewed source controller or Ceph ownership changed")
    return list(identity)


def require_manifest(manifest):
    namespace = manifest.get("namespace")
    if (namespace not in SOURCES or manifest.get("format") != 1 or manifest.get("image") != IMAGE or
            manifest.get("cluster_uid") != common.CLUSTER_UID or manifest.get("identity") != list(SOURCES[namespace]) or
            manifest.get("before") != manifest.get("after") or
            set(manifest.get("files", {})) != {"globals.sql", "database.dump"} or
            any(type(v.get("bytes")) is not int or v["bytes"] <= 0 or
                not re.fullmatch(r"[a-f0-9]{64}", v.get("sha256", "")) for v in manifest["files"].values())):
        raise RuntimeError("protected manifest identity or export contract changed")


def finalize(run_id, manifest):
    point = point_path(run_id)
    require_manifest(manifest)
    if any(protected.file_digest(point / name) != value for name, value in manifest["files"].items()):
        raise RuntimeError("protected export bytes changed")
    protected.write_json(point / "verified.json", manifest)
    return {"point": str(point), "manifest_sha256": digest(common.canonical(manifest)),
            "files": manifest["files"], "namespace": manifest["namespace"]}


def require_quiescence(namespace):
    client = [os.environ.get("KUBECTL", "kubectl")]
    objects = json.loads(common.command([*client, "get", "deployment,cronjob,job,pod", "-n", namespace,
                                         "-o=json"]).stdout)["items"]
    deployments = [o for o in objects if o["kind"] == "Deployment"]
    if len(deployments) != 1 or deployments[0]["metadata"]["name"] != namespace:
        raise RuntimeError("writer ownership changed")
    for obj in objects:
        spec, status = obj.get("spec", {}), obj.get("status", {})
        if ((obj["kind"] == "Deployment" and (spec.get("replicas") != 0 or status.get("replicas", 0) != 0)) or
                (obj["kind"] == "CronJob" and (spec.get("suspend") is not True or status.get("active"))) or
                (obj["kind"] == "Job" and status.get("active", 0)) or
                (obj["kind"] == "Pod" and status.get("phase") not in ("Succeeded", "Failed") and
                 obj["metadata"]["name"] != namespace + "-postgres-0")):
            raise RuntimeError("application writer is not quiesced")
    query = "SELECT count(*) FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid()"
    count = common.command(source_client(namespace, "psql", "-X", "-Atq", "-v", "ON_ERROR_STOP=1", "-c", query,
                                         database=namespace.removesuffix("-canary"))).stdout.strip()
    if count != b"0":
        raise RuntimeError("database still has another client")


def backup(namespace, run_id, quiesced=False):
    identity = source_identity(namespace)
    if quiesced:
        require_quiescence(namespace)
    before = source_metadata(namespace)
    files = {}
    role = namespace.removesuffix("-canary")
    for name, arguments in (("globals.sql", ("pg_dumpall", "--globals-only", "--no-role-passwords", "--no-tablespaces")),
                            ("database.dump", ("pg_dump", "--format=custom", "--create", "--lock-wait-timeout=10s"))):
        producer = receiver = None
        try:
            producer = subprocess.Popen(source_client(namespace, *arguments, database=role),
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            receiver = subprocess.Popen(remote("internal-receive", run_id, "--file", name), stdin=producer.stdout,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            producer.stdout.close()
            output, _ = receiver.communicate()
            _, errors = producer.communicate()
            if producer.returncode or receiver.returncode or errors:
                raise RuntimeError("database export failed or warned; protected partial retained")
            files[name] = json.loads(output)
        finally:
            for process in (receiver, producer):
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    if source_identity(namespace) != identity:
        raise RuntimeError("source identity changed during export")
    if quiesced:
        require_quiescence(namespace)
    manifest = {"format": 1, "namespace": namespace, "cluster_uid": common.CLUSTER_UID, "image": IMAGE,
                "identity": identity, "before": before, "after": source_metadata(namespace), "files": files,
                "source_quiesced": quiesced, "role_passwords_omitted": True}
    return json.loads(common.command(remote("internal-finalize", run_id, "--manifest", json.dumps(manifest))).stdout)


def require_isolation(container, scratch, run_id, mount="/var/lib/postgresql/data"):
    host = container["HostConfig"]
    if (container["Config"].get("Labels", {}).get(LABEL) != run_id or container["Config"].get("User") != "70:70" or
            any(host.get(k) != v for k, v in {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                "CapDrop": ["ALL"], "PidMode": "", "IpcMode": "private", "UTSMode": "", "UsernsMode": ""}.items()) or
            any(host.get(k) for k in ("CapAdd", "Devices", "DeviceRequests", "PortBindings")) or
            host.get("SecurityOpt") != ["no-new-privileges:true"] or
            host.get("Tmpfs") != {"/tmp": "rw,nosuid,nodev"}):
        raise RuntimeError("PostgreSQL restore isolation changed")
    mounts = container.get("Mounts", [])
    if (len(mounts) != 1 or mounts[0].get("Type") != "bind" or mounts[0].get("Source") != str(scratch / "data") or
            mounts[0].get("Destination") != mount or mounts[0].get("RW") is not True):
        raise RuntimeError("PostgreSQL restore mount ownership changed")


def require_image(image, expected=IMAGE):
    mount = "/var/lib/postgresql" if expected == CANDIDATE else "/var/lib/postgresql/data"
    if (expected not in (IMAGE, CANDIDATE) or
            expected not in {protected.canonical_reference(r) for r in image.get("RepoDigests", [])} or
            image.get("Architecture") != "amd64" or image.get("Os") != "linux" or
            set(image["Config"].get("Volumes") or {}) != {mount}):
        raise RuntimeError("reviewed PostgreSQL image architecture or volumes changed")
    return mount


def require_original_restore(point, expected_manifest):
    for path in sorted(point.glob("restore-*.json")):
        protected.protected_file(path)
        result = json.loads(path.read_bytes())
        if (result.get("accepted") and result.get("manifest_sha256") == expected_manifest and
                result.get("version") == "17.11" and result.get("image") == IMAGE and
                all(result.get(k) is True for k in ("schema_matches", "logical_data_matches", "authorization_matches",
                    "offline_checksums_valid", "clean_shutdown", "protected_hashes_unchanged", "production_network_unroutable")) and
                result.get("cleanup", {}).get("scratch_absent") is True and
                result.get("cleanup", {}).get("owned_containers_absent") is True):
            return
    raise RuntimeError("exact original-version restore must pass before candidate qualification")


def restore(run_id, expected_manifest, qualify=False):
    point = point_path(run_id)
    protected.protected_file(point / "verified.json")
    raw = (point / "verified.json").read_bytes()
    manifest = json.loads(raw)
    require_manifest(manifest)
    if digest(raw) != expected_manifest:
        raise RuntimeError("protected manifest hash changed")
    if qualify:
        require_original_restore(point, expected_manifest)
    restore_image, restore_version = (CANDIDATE, "18.6") if qualify else (IMAGE, "17.11")
    if common.docker("ps", "-aq", "--filter=label=" + LABEL).stdout.strip():
        raise RuntimeError("an owned PostgreSQL restore is active; leave it alone")
    before_images = set(common.docker("image", "ls", "-q", "--no-trunc").stdout.decode().split())
    scratch = Path(tempfile.mkdtemp(prefix=run_id + "-restore-", dir=common.ROOT))
    identity = image_id = None
    result = {"accepted": False, "namespace": manifest["namespace"], "manifest_sha256": expected_manifest}
    try:
        data = scratch / "data"
        data.mkdir(mode=0o700)
        os.chown(data, 70, 70)
        for name, value in manifest["files"].items():
            if protected.file_digest(point / name) != value:
                raise RuntimeError("protected backup bytes changed")
            shutil.copyfile(point / name, data / name)
            (data / name).chmod(0o600)
            os.chown(data / name, 70, 70)
        common.docker("pull", restore_image)
        image = json.loads(common.docker("image", "inspect", restore_image).stdout)[0]
        image_id = image["Id"]
        mount = require_image(image, restore_image)
        identity = common.docker("create", "--network=none", "--read-only", "--cap-drop=ALL", "--user=70:70",
                                 "--security-opt=no-new-privileges:true", "--ipc=private", "--pids-limit=128",
                                 "--cpus=1", "--memory=1g", "--label=" + LABEL + "=" + run_id,
                                 "--mount=type=bind,source=" + str(data) + ",target=" + mount,
                                 "--tmpfs=/tmp:rw,nosuid,nodev", "--entrypoint=/bin/sh", restore_image,
                                 "-c", "exec sleep 2147483647").stdout.decode().strip()
        require_isolation(common.inspect(identity), scratch, run_id, mount)
        common.docker("start", identity)
        state = common.inspect(identity)
        require_isolation(state, scratch, run_id, mount)
        net = ["nsenter", "--target", str(state["State"]["Pid"]), "--net", "--"]
        links = json.loads(common.command([*net, "ip", "-j", "address"]).stdout)
        routes = sum((json.loads(common.command([*net, "ip", f, "-j", "route", "show", "table", "all"]).stdout)
                      for f in ("-4", "-6")), [])
        common.require_network(links, routes)
        if common.command([*net, "ip", "route", "get", "10.0.20.50"], check=False).returncode == 0:
            raise RuntimeError("restore can route to production")
        def execute(*args, check=True, input=None):
            command = ["docker", "exec", "-i", identity, *args]
            p = subprocess.run(command, input=input, capture_output=True)
            if check and p.returncode:
                # Keep SQL/data-bearing diagnostics only with protected recovery material.
                protected.write_json(point / ("diagnostic-" + str(time.time_ns()) + ".json"),
                                     {"command": args[0], "exit": p.returncode,
                                      "stdout": p.stdout.decode(errors="replace"),
                                      "stderr": p.stderr.decode(errors="replace")})
                raise RuntimeError("isolated PostgreSQL command failed: " + args[0] + ":" + str(p.returncode) +
                                   "; classes=" + ",".join(error_class(p.stderr)))
            return p.stdout
        if execute("postgres", "--version").strip() != ("postgres (PostgreSQL) " + restore_version).encode():
            raise RuntimeError("restore executable version changed")
        root = mount
        pgdata = root + "/restored"
        execute("initdb", "-D", pgdata, "--username=" + ADMIN, "--auth-local=trust", "--auth-host=reject",
                "--encoding=UTF8", "--locale=en_US.utf8", "--data-checksums")
        execute("pg_ctl", "-D", pgdata, "-l", "/tmp/recovery.log", "-o",
                "-c listen_addresses='' -c unix_socket_directories=/tmp -c unix_socket_permissions=0700", "-w", "start")
        execute("createdb", "-h", "/tmp", "-U", ADMIN, CONTROL)
        execute("psql", "-X", "-h", "/tmp", "-U", ADMIN, "-d", CONTROL, "-v", "ON_ERROR_STOP=1",
                "-f", root + "/globals.sql")
        execute("pg_restore", "-h", "/tmp", "-U", ADMIN, "--exit-on-error", "--create", "-d", CONTROL,
                root + "/database.dump")
        database = manifest["namespace"].removesuffix("-canary")
        schema = execute("pg_dump", "-h", "/tmp", "-U", ADMIN, "-d", database, "--schema-only", "--no-comments")
        if digest(normalized_dump(schema)) != manifest["before"]["schema_sha256"]:
            raise RuntimeError("restored application schema fingerprint differs")
        def sql(query):
            return execute("psql", "-X", "-h", "/tmp", "-U", ADMIN, "-d", database,
                           "-Atq", "-v", "ON_ERROR_STOP=1", input=query.encode())
        if sql(ROLE_SQL).decode().strip() != manifest["before"]["roles_sha256"]:
            raise RuntimeError("restored password-free authorization fingerprint differs")
        archived = execute("pg_restore", "--data-only", "--no-comments", "--file=-", root + "/database.dump")
        restored = execute("pg_dump", "-h", "/tmp", "-U", ADMIN, "-d", database, "--data-only", "--no-comments")
        comparison = data_diagnostic(archived, restored)
        result["data_diagnostic"] = comparison
        if not all(comparison[key] for key in ("copy_multiset_equal", "session_settings_equal", "sequence_commands_equal")):
            raise RuntimeError("restored complete logical data fingerprint differs")
        counts = [int(n) for n in sql(ROW_SQL).splitlines()]
        if len(counts) != manifest["before"]["features"]["user_tables"]:
            raise RuntimeError("restored user relation count changed")
        require_isolation(common.inspect(identity), scratch, run_id, mount)
        execute("pg_ctl", "-D", pgdata, "-w", "-m", "fast", "stop")
        execute("test", "!", "-e", pgdata + "/postmaster.pid")
        execute("pg_checksums", "--check", "-D", pgdata)
        if any(protected.file_digest(point / name) != value for name, value in manifest["files"].items()):
            raise RuntimeError("original protected files changed during restore")
        result.update(accepted=True, version=restore_version, image=restore_image, candidate_qualification=qualify,
                      relations=len(counts), rows=sum(counts),
                      schema_matches=True, logical_data_matches=True, authorization_matches=True,
                      offline_checksums_valid=True, clean_shutdown=True, protected_hashes_unchanged=True,
                      production_network_unroutable=True)
    except Exception as error:
        result["error"] = str(error)
    finally:
        if identity:
            require_isolation(common.inspect(identity), scratch, run_id, mount)
            common.docker("rm", "-f", identity)
        shutil.rmtree(scratch)
        removed = False
        if image_id and image_id not in before_images:
            if not common.docker("ps", "-aq", "--filter=ancestor=" + image_id).stdout.strip():
                common.docker("image", "rm", image_id)
                removed = common.docker("image", "inspect", image_id, check=False).returncode != 0
                if not removed:
                    raise RuntimeError("owned PostgreSQL image remains")
        result["cleanup"] = {"scratch_absent": not scratch.exists(), "new_image_removed": removed,
                             "owned_containers_absent": not common.docker("ps", "-aq", "--filter=label=" + LABEL).stdout.strip()}
    protected.write_json(point / ("restore-" + str(time.time_ns()) + ".json"), result)
    return result


def main():
    def interrupted(_number, _frame):
        raise InterruptedError("PostgreSQL recovery interrupted")
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, interrupted)
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("backup", "restore", "internal-receive", "internal-finalize", "internal-restore"))
    parser.add_argument("--run-id", type=common.run_identifier, required=True)
    parser.add_argument("--namespace", choices=sorted(SOURCES))
    parser.add_argument("--file", choices=("globals.sql", "database.dump"))
    parser.add_argument("--manifest")
    parser.add_argument("--qualify-18-6", action="store_true")
    parser.add_argument("--quiesced", action="store_true")
    args = parser.parse_args()
    if args.qualify_18_6 and args.mode not in ("restore", "internal-restore"):
        parser.error("candidate qualification requires restore mode")
    if args.quiesced and args.mode != "backup":
        parser.error("quiescence applies only to a new backup")
    os.umask(0o077)
    if args.mode == "backup":
        if not args.namespace:
            parser.error("backup requires namespace")
        result = backup(args.namespace, args.run_id, args.quiesced)
    elif args.mode == "restore":
        if not args.manifest or not re.fullmatch(r"[a-f0-9]{64}", args.manifest):
            parser.error("restore requires exact manifest hash")
        extra = ["--qualify-18-6"] if args.qualify_18_6 else []
        response = common.command(remote("internal-restore", args.run_id, "--manifest", args.manifest, *extra), check=False)
        result = json.loads(response.stdout)
        if response.returncode and result.get("accepted"):
            raise RuntimeError("remote exit contradicts restore receipt")
    elif args.mode == "internal-receive":
        if not args.file:
            parser.error("receiver requires file")
        result = receive(args.run_id, args.file)
    elif args.mode == "internal-finalize":
        result = finalize(args.run_id, json.loads(args.manifest))
    else:
        result = restore(args.run_id, args.manifest, args.qualify_18_6)
    print(json.dumps(result), flush=True)
    return 0 if result.get("accepted", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
