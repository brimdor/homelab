#!/usr/bin/env python3
"""Test recovery ownership, complete slots, expiry accounting and data isolation."""

import copy
from pathlib import Path
import subprocess
import unittest

import valkey_recovery as recovery


class ValkeyRecoveryTests(unittest.TestCase):
    def manifest(self):
        return {"format": 1, "cluster_uid": recovery.common.CLUSTER_UID, "owner_uid": recovery.OWNER,
                "image": recovery.IMAGE, "cross_shard_atomic": False, "source_quiesced": False,
                "shards": {k: {"pod_uid": uid, "pvc_uid": recovery.CLAIMS[k][0], "pv_uid": recovery.CLAIMS[k][1],
                                "bytes": 100, "sha256": "a" * 64, "topology_sha256": "b" * 64}
                           for k, uid in recovery.MASTERS.items()}}

    def fixture(self):
        return {"Config": {"Labels": {recovery.LABEL: "synthetic"}, "User": "1001:1001"},
                "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Privileged": False,
                               "CapDrop": ["ALL"], "PidMode": "", "IpcMode": "private", "UTSMode": "", "UsernsMode": "",
                               "SecurityOpt": ["no-new-privileges:true"], "Tmpfs": {"/tmp": "rw,nosuid,nodev"}},
                "Mounts": [{"Type": "bind", "Source": "/synthetic/data", "Destination": "/bitnami/valkey/data", "RW": True}]}

    def topology(self):
        lines = []
        for i, slots in enumerate(("0-5460", "5461-10922", "10923-16383")):
            master, replica = str(i + 1) * 40, str(i + 4) * 40
            lines += [f"{master} private:6379 master - 1 2 3 connected {slots}",
                      f"{replica} private:6379 slave {master} 1 2 3 connected"]
        return "\n".join(lines).encode()

    def test_topology_ignores_volatile_ping_times_addresses_and_self_marker(self):
        value = self.topology()
        changed = value.replace(b" 1 2 3 ", b" 9 8 7 ").replace(b"private", b"other").replace(b" master ", b" myself,master ")
        self.assertEqual(recovery.topology(value), recovery.topology(changed))

    def test_incomplete_duplicate_migrating_or_disconnected_slots_are_refused(self):
        value = self.topology()
        for changed in (value.replace(b"0-5460", b"1-5460"), value.replace(b"5461-10922", b"5460-10922"),
                        value.replace(b"connected", b"disconnected", 1), value.replace(b"master -", b"master,fail -", 1),
                        value.replace(b"0-5460", b"[1->-private]"), value.replace(b"10923-16383", b"10923-16384")):
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                recovery.topology(changed)

    def test_manifest_binds_source_cluster_owner_image_all_shards_and_claims(self):
        value = self.manifest()
        recovery.require_manifest(value)
        for key, replacement in (("cluster_uid", "wrong"), ("owner_uid", "wrong"), ("image", "other:latest"),
                                 ("cross_shard_atomic", True), ("source_quiesced", True), ("format", 2)):
            changed = copy.deepcopy(value)
            changed[key] = replacement
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                recovery.require_manifest(changed)
        for key, replacement in (("pod_uid", "wrong"), ("pvc_uid", "wrong"), ("pv_uid", "wrong"),
                                 ("bytes", 0), ("sha256", "wrong"), ("topology_sha256", "c" * 64)):
            changed = copy.deepcopy(value)
            changed["shards"]["0"][key] = replacement
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                recovery.require_manifest(changed)

    def test_network_privilege_and_mount_changes_are_refused(self):
        recovery.require_isolation(self.fixture(), Path("/synthetic"), "synthetic", "/bitnami/valkey/data")
        for key, value in (("NetworkMode", "host"), ("ReadonlyRootfs", False), ("Privileged", True),
                           ("CapDrop", []), ("CapAdd", ["SYS_ADMIN"]), ("PidMode", "host"), ("IpcMode", "host"),
                           ("UsernsMode", "host"), ("UTSMode", "host"), ("Devices", [{}]),
                           ("DeviceRequests", [{}]), ("PortBindings", {"6379/tcp": []}),
                           ("SecurityOpt", []), ("Tmpfs", {"/tmp": "rw"})):
            changed = self.fixture()
            changed["HostConfig"][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                recovery.require_isolation(changed, Path("/synthetic"), "synthetic", "/bitnami/valkey/data")
        for key, value in (("Source", "/real-data"), ("Destination", "/real-data"), ("Type", "volume"), ("RW", False)):
            changed = self.fixture()
            changed["Mounts"][0][key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                recovery.require_isolation(changed, Path("/synthetic"), "synthetic", "/bitnami/valkey/data")

    def test_image_identity_architecture_and_unowned_volumes_are_refused(self):
        image = {"Os": "linux", "Architecture": "amd64", "RepoDigests": [recovery.IMAGE.replace("docker.io/", "")],
                 "Config": {"Volumes": {"/bitnami/valkey/data": {}}}}
        self.assertEqual(recovery.image_mount(image), "/bitnami/valkey/data")
        for key, value in (("Os", "other"), ("Architecture", "arm64"), ("RepoDigests", []),
                           ("Config", {"Volumes": {"/unreviewed": {}}})):
            changed = copy.deepcopy(image)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                recovery.image_mount(changed)

    def test_checksum_and_key_inventory_are_both_required_without_private_error_output(self):
        result = subprocess.CompletedProcess([], 0, b"[info] Checksum OK\n[info] 123 keys read\n", b"")
        self.assertEqual(recovery.checked_keys(result), 123)
        for result in (subprocess.CompletedProcess([], 1, b"private key contents", b"private failure"),
                       subprocess.CompletedProcess([], 0, b"123 keys read", b""),
                       subprocess.CompletedProcess([], 0, b"Checksum OK", b"")):
            with self.assertRaises(RuntimeError) as caught:
                recovery.checked_keys(result)
            self.assertNotIn("private", str(caught.exception))

    def test_expired_keys_are_explicitly_accounted_without_claiming_live_data_equality(self):
        persistence = {"rdb_last_load_keys_loaded": "95", "rdb_last_load_keys_expired": "5"}
        result = recovery.load_counts(persistence, {"db0": "keys=90,expires=80,avg_ttl=1000"}, 100)
        self.assertEqual(result, {"checked_keys": 100, "loaded_keys": 95, "expired_at_load": 5,
                                 "current_keys": 90, "expired_after_load": 5})
        for expected, keyspace in ((101, {"db0": "keys=90,expires=80"}), (100, {"db0": "keys=96,expires=80"})):
            with self.assertRaises(RuntimeError):
                recovery.load_counts(persistence, keyspace, expected)


if __name__ == "__main__":
    unittest.main()
