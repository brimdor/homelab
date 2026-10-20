#!/usr/bin/env python3
"""Native SQLite snapshot regression: complete types, metadata and framing."""
import io
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import sqlite_recovery as recovery

NODE = os.environ.get("NODE") or shutil.which("node")
PROGRAM = Path(recovery.__file__).with_suffix(".cjs").read_text()


@unittest.skipUnless(NODE, "native Node.js >=22.16 is required")
class SnapshotTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.database = self.root / "source.sqlite"
        fixture = r"""const {DatabaseSync}=require('node:sqlite');const db=new DatabaseSync(process.argv[1]);
        db.exec("PRAGMA journal_mode=WAL;CREATE TABLE parent(id INTEGER PRIMARY KEY, content TEXT);CREATE TABLE child(id INTEGER, parent_id INTEGER REFERENCES parent(id), n REAL, b BLOB);CREATE TABLE no_rowid(id TEXT PRIMARY KEY, payload TEXT) WITHOUT ROWID;CREATE VIEW summary AS SELECT count(*) AS n FROM child;CREATE TRIGGER parent_added AFTER INSERT ON parent BEGIN INSERT INTO no_rowid VALUES (CAST(new.id AS TEXT),'trigger');END;");
        db.prepare('INSERT INTO parent VALUES (?,?)').run(9007199254740993n,'NUL\u0000 Unicode é 🚀');
        const insert=db.prepare('INSERT INTO child VALUES (?,?,?,?)');
        for(let i=0;i<2;i++)insert.run(7,9007199254740993n,1.25,Buffer.from([0,255,1]));db.close();"""
        self.native(fixture, str(self.database))

    def native(self, program, *args, success=True):
        result = subprocess.run([NODE, "--disable-warning=ExperimentalWarning", "-e", program, *args], capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual(result.stderr, b"")
        else:
            self.assertNotEqual(result.returncode, 0)
        return result.stdout

    def capture(self):
        return self.native(PROGRAM, "capture", str(self.database), str(self.root))

    def test_native_copy_preserves_types_duplicates_rowids_schema_and_metadata(self):
        data = self.capture()
        header = recovery.receive_database(io.BytesIO(data), self.root / "copy.sqlite")
        self.assertEqual(header["snapshot"]["tables"], 3)
        self.assertEqual(header["snapshot"]["rows"], 4)
        readonly = self.root / "readonly"; readonly.mkdir()
        original = readonly / "database.sqlite"; (self.root / "copy.sqlite").rename(original)
        original.chmod(0o400); readonly.chmod(0o500)
        try:
            result = json.loads(self.native(PROGRAM, "restore", str(original), str(self.root), json.dumps(header["snapshot"])))
            self.assertEqual([p.name for p in readonly.iterdir()], ["database.sqlite"])
        finally:
            readonly.chmod(0o700); original.chmod(0o600)
        self.assertTrue(result["accepted"])
        self.assertTrue(result["integrity_valid"])
        self.assertEqual(result["snapshot"], header["snapshot"])
        self.assertEqual(list(self.root.glob(".sqlite-recovery-103-*")), [])

    def test_invalid_frames_and_symlink_destinations_refused(self):
        data = self.capture()
        for name, damaged in (("truncated", data[:-20]), ("trailing", data + b"extra"),
                              ("corrupt", data.replace(b"SQLite format 3", b"SQLite FORMAT 3", 1))):
            with self.subTest(name=name), self.assertRaises((RuntimeError, ValueError)):
                recovery.receive_database(io.BytesIO(damaged), self.root / (name + ".sqlite"))
        link = self.root / "link.sqlite"; link.symlink_to(self.database)
        with self.assertRaises(RuntimeError):
            recovery.receive_database(io.BytesIO(data), link)

    def test_wrong_snapshot_refused_and_owned_native_scratch_removed(self):
        header = recovery.receive_database(io.BytesIO(self.capture()), self.root / "copy.sqlite")
        header["snapshot"]["data_sha256"] = "0" * 64
        self.native(PROGRAM, "restore", str(self.root / "copy.sqlite"), str(self.root), json.dumps(header["snapshot"]), success=False)
        self.assertEqual(list(self.root.glob(".sqlite-recovery-103-*")), [])

    def test_missing_source_never_initializes_database(self):
        missing = self.root / "missing.sqlite"
        self.native(PROGRAM, "capture", str(missing), str(self.root), success=False)
        self.assertFalse(missing.exists())
        self.assertEqual(list(self.root.glob(".sqlite-recovery-103-*")), [])

    def test_large_snapshot_stream_has_complete_payload_and_final_commit(self):
        self.native("const {DatabaseSync}=require('node:sqlite');const db=new DatabaseSync(process.argv[1]);"
                    "db.exec('CREATE TABLE bulk(data BLOB);BEGIN');const s=db.prepare('INSERT INTO bulk VALUES (zeroblob(1048576))');"
                    "for(let i=0;i<200;i++)s.run();db.exec('COMMIT');db.close();", str(self.database))
        child = subprocess.Popen([NODE, "--disable-warning=ExperimentalWarning", "-e", PROGRAM,
                                  "capture", str(self.database), str(self.root), "acknowledged"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            def prepared(commit):
                child.stdin.write((commit + '\n').encode()); child.stdin.flush()
            header = recovery.receive_database(child.stdout, self.root / "large-copy.sqlite", self.root / "header.json", prepared)
            child.stdin.close(); child.stdin = None
            _, error = child.communicate()
            self.assertEqual((child.returncode, error), (0, b""))
            self.assertGreater(header["bytes"], 200 * 1048576)
            self.assertEqual(header["snapshot"]["rows"], 204)
            self.assertEqual(json.loads((self.root / "header.json").read_text()), header)
        finally:
            if child.poll() is None:
                child.terminate(); child.wait()
            child.stdout.close(); child.stderr.close()
        self.assertEqual(list(self.root.glob(".sqlite-recovery-103-*")), [])

    def test_wrong_transfer_acknowledgement_refused_and_scratch_removed(self):
        child = subprocess.Popen([NODE, "--disable-warning=ExperimentalWarning", "-e", PROGRAM,
                                  "capture", str(self.database), str(self.root), "acknowledged"],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            def prepared(_commit):
                child.stdin.write(b'wrong\n'); child.stdin.flush()
            recovery.receive_database(child.stdout, self.root / 'wrong-ack.sqlite', prepared=prepared)
            child.stdin.close(); child.stdin = None
            _, error = child.communicate()
            self.assertNotEqual(child.returncode, 0)
            self.assertIn(b'stage=transfer_acknowledgement', error)
        finally:
            if child.poll() is None:
                child.terminate(); child.wait()
            child.stdout.close(); child.stderr.close()
        self.assertEqual(list(self.root.glob('.sqlite-recovery-103-*')), [])


class CaptureDiagnosticTest(unittest.TestCase):
    def test_partial_capture_preserves_validated_header_and_never_finalizes(self):
        header = {"format": 1, "bytes": 10, "sha256": "a" * 64,
                  "snapshot": {"tables": 1, "rows": 0, "schema_sha256": "b" * 64,
                               "data_sha256": "c" * 64, "metadata_sha256": "d" * 64, "sqlite_version": "3.51.3"}}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, 'truncated SQLite snapshot'):
                recovery.receive_database(io.BytesIO(json.dumps(header).encode() + b'\nshort'),
                                          root / 'database.sqlite', root / 'header.json')
            self.assertEqual(json.loads((root / 'header.json').read_text()), header)
            self.assertEqual((root / 'database.sqlite').stat().st_size, 5)
            self.assertFalse((root / 'capture.json').exists())

    def test_failure_reports_only_exit_codes_and_fixed_public_diagnostics(self):
        native = b'SQLite recovery failed; stage=stream_payload; type=Error; code=EPIPE; no production records emitted\n'
        error = b'secret-record-content\nRuntimeError: truncated SQLite snapshot\n'
        result = str(recovery.capture_failure(1, 1, native, error))
        self.assertIn('producer_exit=1; receiver_exit=1; receiver=truncated_payload', result)
        self.assertIn('stage=stream_payload', result)
        self.assertNotIn('secret-record-content', result)
        self.assertIn('native_diagnostic_unavailable', str(recovery.capture_failure(1, 1,
                      native.replace(b'stream_payload', b'secret_record_content'), error)))


class KeyBindingTest(unittest.TestCase):
    def test_reviewed_canary_emptydir_refuses_backend_mount_and_restart_changes(self):
        expected = recovery.SOURCES['strata-canary']
        pod = {'metadata': {'uid': expected['pod_uid'], 'name': 'reviewed-source'},
               'spec': {'nodeName': 'pikachu', 'volumes': [{'name': 'data', 'emptyDir': {}}],
                        'containers': [{'name': 'main', 'volumeMounts': [{'name': 'data', 'mountPath': '/app/data'}]}]},
               'status': {'containerStatuses': [{'name': 'main', 'ready': True, 'restartCount': 0,
                                                 'imageID': expected['image']}]}}
        def kube(*args):
            return {'metadata': {'uid': recovery.common.CLUSTER_UID}} if args[1] == 'namespace' else {'items': [pod]}
        with patch.object(recovery, 'kube', side_effect=kube):
            self.assertEqual(recovery.source_identity('strata-canary')['data_storage'], 'emptyDir')
            for backend in ({'nfs': {'server': '10.0.40.3', 'path': '/protected'}},
                            {'persistentVolumeClaim': {'claimName': 'unreviewed'}}, {'emptyDir': {'medium': 'Memory'}}):
                pod['spec']['volumes'] = [{'name': 'data', **backend}]
                with self.assertRaisesRegex(RuntimeError, 'emptyDir ownership changed'):
                    recovery.source_identity('strata-canary')
            pod['spec']['volumes'] = [{'name': 'data', 'emptyDir': {}}]
            pod['status']['containerStatuses'][0]['restartCount'] = 1
            with self.assertRaisesRegex(RuntimeError, 'emptyDir ownership changed'):
                recovery.source_identity('strata-canary')
            pod['status']['containerStatuses'][0]['restartCount'] = 0
            pod['spec']['containers'][0]['volumeMounts'][0]['subPath'] = 'different'
            with self.assertRaisesRegex(RuntimeError, 'emptyDir ownership changed'):
                recovery.source_identity('strata-canary')

    def test_in_memory_remote_program_needs_no_source_file_path(self):
        with patch.dict(recovery.__dict__, {"NODE_PROGRAM": "reviewed-native-program"}), patch.object(recovery, "__file__", None):
            self.assertEqual(recovery.program("humbleai-demo"), "reviewed-native-program")

    def test_demo_key_field_binds_the_distinct_runtime_environment_name(self):
        key = recovery.SOURCES["humbleai-demo"]["key"]
        data = b"synthetic-demo-key"
        secret = {"metadata": {"uid": key["uid"]}, "data": {key["field"]: base64.b64encode(data).decode()}}
        response = SimpleNamespace(stdout=hashlib.sha256(data).hexdigest().encode())
        with patch.object(recovery, "kube", return_value=secret), patch.object(recovery.common, "command", return_value=response) as command:
            self.assertEqual(recovery.declared_key("humbleai-demo", {"pod": "reviewed-source"}), data)
            self.assertEqual(command.call_args.args[0][-1], "OPENAI_ENCRYPTION_KEY")

    def test_demo_container_layer_contract_refuses_new_mounts_or_restarts(self):
        expected = {**recovery.SOURCES["humbleai-demo"], "pvc": None}
        pod = {"metadata": {"uid": expected["pod_uid"], "name": "reviewed-source"},
               "spec": {"nodeName": "pikachu", "containers": [{"name": "main"}]},
               "status": {"containerStatuses": [{"name": "main", "ready": True, "restartCount": 0,
                                                 "imageID": expected["image"]}]}}
        def kube(*args):
            return {"metadata": {"uid": recovery.common.CLUSTER_UID}} if args[1] == "namespace" else {"items": [pod]}
        with patch.dict(recovery.SOURCES, {"humbleai-demo": expected}), patch.object(recovery, "kube", side_effect=kube):
            self.assertEqual(recovery.source_identity("humbleai-demo")["data_storage"], "container-layer")
            pod["spec"]["volumes"] = [{"name": "unexpected"}]
            with self.assertRaisesRegex(RuntimeError, "ownership changed"):
                recovery.source_identity("humbleai-demo")
            del pod["spec"]["volumes"]
            pod["status"]["containerStatuses"][0]["restartCount"] = 1
            with self.assertRaisesRegex(RuntimeError, "ownership changed"):
                recovery.source_identity("humbleai-demo")

    def test_retained_demo_mount_and_volume_identity_must_match(self):
        expected = recovery.SOURCES["humbleai-demo"]
        pod = {"metadata": {"uid": expected["pod_uid"], "name": "reviewed-source"},
               "spec": {"nodeName": "growlithe", "containers": [{"name": "main", "volumeMounts": [{"name": "data", "mountPath": "/app/server/data"}]}],
                        "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": expected["pvc"]}}]},
               "status": {"containerStatuses": [{"name": "main", "ready": True, "restartCount": 0, "imageID": expected["image"]}]}}
        claim = {"metadata": {"uid": expected["pvc_uid"]}, "status": {"phase": "Bound"},
                 "spec": {"volumeName": "reviewed-volume", "storageClassName": "standard-rwo"}}
        volume = {"metadata": {"uid": expected["pv_uid"]}, "spec": {"csi": {"driver": "rook-ceph.rbd.csi.ceph.com"},
                  "claimRef": {"uid": expected["pvc_uid"]}}}
        def kube(*args):
            return {'namespace': {"metadata": {"uid": recovery.common.CLUSTER_UID}}, 'pods': {"items": [pod]},
                    'pvc': claim, 'pv': volume}[args[1]]
        with patch.object(recovery, "kube", side_effect=kube):
            self.assertEqual(recovery.source_identity("humbleai-demo")["pvc_uid"], expected["pvc_uid"])
            volume['spec']['claimRef']['uid'] = 'different-owner'
            with self.assertRaisesRegex(RuntimeError, 'Ceph ownership changed'):
                recovery.source_identity('humbleai-demo')

    def test_only_reviewed_historical_and_current_sources_restore(self):
        expected = recovery.SOURCES['humbleai-demo']
        for uid in [expected['pod_uid'], *expected['previous_pod_uids']]:
            recovery.require_restore_source({'source': {'namespace': 'humbleai-demo', 'pod_uid': uid, 'image': expected['image']}}, 'humbleai-demo')
        with self.assertRaisesRegex(RuntimeError, 'restore source differs'):
            recovery.require_restore_source({'source': {'namespace': 'humbleai-demo', 'pod_uid': 'unreviewed', 'image': expected['image']}}, 'humbleai-demo')

    def test_declared_key_must_match_same_secret_uid_and_running_process(self):
        data = b"synthetic-encryption-material"
        key = recovery.SOURCES["second-brain"]["key"]
        secret = {"metadata": {"uid": key["uid"]}, "data": {key["field"]: base64.b64encode(data).decode()}}
        command = SimpleNamespace(stdout=hashlib.sha256(data).hexdigest().encode())
        with patch.object(recovery, "kube", return_value=secret), patch.object(recovery.common, "command", return_value=command):
            self.assertEqual(recovery.declared_key("second-brain", {"pod": "reviewed-source"}), data)
            command.stdout = b"0" * 64
            with self.assertRaisesRegex(RuntimeError, "differs from the running application"):
                recovery.declared_key("second-brain", {"pod": "reviewed-source"})
            secret["metadata"]["uid"] = "another-secret"
            with self.assertRaisesRegex(RuntimeError, "identity changed"):
                recovery.declared_key("second-brain", {"pod": "reviewed-source"})


class ImageContractTest(unittest.TestCase):
    def test_only_the_exact_reviewed_strata_image_volume_is_allowed(self):
        for namespace in ('strata', 'strata-canary'):
            image = {'Architecture': 'amd64', 'Os': 'linux', 'Config': {'Volumes': {'/app/data': {}}},
                     'RepoDigests': [recovery.SOURCES[namespace]['image']]}
            self.assertEqual(recovery.require_image(image, namespace)['architecture'], 'amd64')
            for wrong in (None, {'/': {}}, {'/app/data': {}, '/unexpected': {}}):
                with self.assertRaises(RuntimeError):
                    recovery.require_image({**image, 'Config': {'Volumes': wrong}}, namespace)

    def test_exact_architecture_digest_and_existing_emulation_required(self):
        source = recovery.SOURCES["second-brain"]
        image = {"Architecture": "arm64", "Os": "linux", "Config": {"Volumes": None},
                 "RepoDigests": [source["image"]]}
        handler = ("enabled\ninterpreter /usr/bin/qemu-aarch64-static\nflags: F\noffset 0\n"
                   "magic 7f454c460201010000000000000000000200b700\n"
                   "mask ffffffffffffff00fffffffffffffffffeffffff\n").encode()
        with patch.object(Path, "read_bytes", return_value=handler):
            self.assertEqual(recovery.require_image(image, "second-brain")["architecture"], "arm64")
            for key, wrong in (("Architecture", "amd64"), ("Os", "other"), ("RepoDigests", []),
                               ("Config", {"Volumes": {"/unexpected": {}}})):
                with self.subTest(key=key), self.assertRaises(RuntimeError):
                    recovery.require_image({**image, key: wrong}, "second-brain")
        with patch.object(Path, "read_bytes", return_value=handler.replace(b"flags: F", b"flags:")):
            with self.assertRaisesRegex(RuntimeError, "emulation changed"):
                recovery.require_image(image, "second-brain")


if __name__ == "__main__":
    unittest.main()
