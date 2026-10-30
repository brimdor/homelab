#!/usr/bin/env python3
"""Reject unrelated storage, runtime and version profiles before backup work."""
import copy
import unittest
import central_postgres_recovery as recovery


class BridgeProfileTests(unittest.TestCase):
    def setUp(self):
        self.original = (recovery.SOURCE_UID, recovery.SOURCE_CONTAINER,
                         recovery.CAPTURE_VERSION, recovery.RESTORE_VERSION)
        self.profile = {
            "format": 1, "node": "totodile",
            "node_uid": "83e0e536-e94a-45a1-8dfb-1cedac1e9bd7",
            "source_version": "v1.33.6+k3s1", "receiver_version": "v1.33.10+k3s1",
            "pvc_uid": recovery.PVC_UID, "pv_uid": recovery.PV_UID,
            "system_identifier": recovery.SYSTEM_ID, "image": recovery.IMAGE,
            "pod_uid": "b125240b-aac3-494b-aa18-664db846ca5b", "container_id": "a"*64,
        }

    def tearDown(self):
        (recovery.SOURCE_UID, recovery.SOURCE_CONTAINER,
         recovery.CAPTURE_VERSION, recovery.RESTORE_VERSION) = self.original

    def test_fresh_runtime_keeps_original_database_identity(self):
        recovery.configure_profile(self.profile)
        self.assertEqual(recovery.SOURCE_UID, self.profile["pod_uid"])
        self.assertEqual(recovery.SOURCE_CONTAINER, self.profile["container_id"])
        self.assertEqual(recovery.CAPTURE_VERSION, "v1.33.6+k3s1")
        self.assertEqual(recovery.RESTORE_VERSION, "v1.33.10+k3s1")
        status = {"status": {"id": recovery.SOURCE_CONTAINER, "state": "CONTAINER_RUNNING",
                           "imageRef": recovery.IMAGE,
                           "labels": {"io.kubernetes.pod.uid": recovery.SOURCE_UID,
                                      "io.kubernetes.pod.namespace": "postgres",
                                      "io.kubernetes.container.name": "main"}}, "info": {"pid": 123}}
        self.assertEqual(recovery.source_runtime(status), 123)
        status["status"]["id"] = "b"*64
        with self.assertRaisesRegex(RuntimeError, "source changed"):
            recovery.source_runtime(status)

    def test_other_identity_storage_version_or_extra_field_refused_atomically(self):
        wrong = {key: "wrong" for key in self.profile}
        wrong.update(format=True, extra=True, source_version="v1.33.13+k3s2",
                     receiver_version="v1.33.6+k3s1", container_id="../container")
        for key, value in wrong.items():
            with self.subTest(key=key):
                changed = copy.deepcopy(self.profile)
                changed[key] = value
                with self.assertRaisesRegex(RuntimeError, "unreviewed"):
                    recovery.configure_profile(changed)
                self.assertEqual((recovery.SOURCE_UID, recovery.SOURCE_CONTAINER,
                                  recovery.CAPTURE_VERSION, recovery.RESTORE_VERSION), self.original)

    def test_missing_profile_member_refused_atomically(self):
        for key in self.profile:
            with self.subTest(key=key):
                changed = dict(self.profile)
                del changed[key]
                with self.assertRaisesRegex(RuntimeError, "unreviewed"):
                    recovery.configure_profile(changed)
                self.assertEqual((recovery.SOURCE_UID, recovery.SOURCE_CONTAINER,
                                  recovery.CAPTURE_VERSION, recovery.RESTORE_VERSION), self.original)


if __name__ == "__main__":
    unittest.main()
