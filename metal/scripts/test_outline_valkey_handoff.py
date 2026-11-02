#!/usr/bin/env python3
"""Focused handoff refusals; synthetic identities and commands, no real data."""

import copy
import unittest
from unittest.mock import patch

import outline_valkey_handoff as handoff


class Backend:
    def __init__(self):
        self.identity_value = {"synthetic": True}
        self.calls = []
        self.values = {}
        base = {"valkey_version": "9.1.3", "cluster_enabled": "0", "loading": "0", "aof_enabled": "1",
                "aof_last_write_status": "ok", "aof_last_bgrewrite_status": "ok", "aof_rewrite_in_progress": "0",
                "aof_rewrite_scheduled": "0", "master_failover_state": "no-failover", "master_replid": "a" * 40,
                "master_repl_offset": "10"}
        self.values["source"] = dict(base, run_id="b" * 40, role="master", connected_slaves="1",
                                     slave0="ip=10.0.1.2,port=6379,state=online,offset=10,lag=0")
        self.values["destination"] = dict(base, run_id="c" * 40, role="slave", master_host="10.0.1.1",
                                          master_port="6379", master_link_status="up", master_sync_in_progress="0",
                                          slave_repl_offset="10", connected_slaves="0")

    def identity(self):
        return copy.deepcopy(self.identity_value)

    def info(self, side):
        return copy.deepcopy(self.values[side])

    def cli(self, side, *args):
        self.calls.append((side, args))
        if args[0] == "FAILOVER":
            self.values["destination"].update(role="master", connected_slaves="1", master_replid="d" * 40,
                master_replid2="a" * 40, second_repl_offset="11", slave0="ip=10.0.1.1,port=6379,state=online,offset=10,lag=0")
            self.values["source"].update(role="slave", connected_slaves="0", master_replid="d" * 40,
                master_host="10.0.1.2", master_port="6379", master_link_status="up", master_sync_in_progress="0", slave_repl_offset="10")
        return "OK"


def plan(backend):
    return {"identity": backend.identity(), "source_ip": "10.0.1.1", "destination_ip": "10.0.1.2",
            "run_ids": {"source": "b" * 40, "destination": "c" * 40}, "original_replid": "a" * 40,
            "recovery_manifest": handoff.MANIFEST}


class Journal:
    def __init__(self, backend, phase=3):
        self.entries = []
        data = [plan(backend), {"target_ip": "10.0.1.1"}, {"primary_replid": "a" * 40},
                {"replid": "a" * 40, "offset": 10, "target_ip": "10.0.1.2", "timeout_ms": 15000, "force": False}]
        for step, value in zip(handoff.STEPS[:phase], data):
            self("append", {"step": step, "previous": handoff.digest(self.entries[-1]) if self.entries else None, "data": value})

    def __call__(self, operation="read", payload=None):
        if operation == "append":
            handoff.require(payload["step"] == handoff.STEPS[len(self.entries)] and
                            payload["previous"] == (handoff.digest(self.entries[-1]) if self.entries else None), "stale journal")
            self.entries.append(copy.deepcopy(payload))
        return copy.deepcopy(self.entries)


class HandoffTests(unittest.TestCase):
    def test_exact_nonforced_command_and_complete_observation(self):
        backend = Backend()
        journal = Journal(backend)
        result = handoff.execute("failover", backend, journal)
        self.assertEqual(result[-1]["step"], "failover-accepted")
        self.assertEqual(backend.calls, [("source", ("FAILOVER", "TO", "10.0.1.2", "6379", "TIMEOUT", "15000"))])
        handoff.execute("failover", backend, journal)
        self.assertEqual(len(backend.calls), 1)
        with self.assertRaisesRegex(RuntimeError, "already dispatched"):
            handoff.execute("replicate", backend, journal)

    def test_uncertain_dispatch_never_replayed(self):
        backend = Backend()
        journal = Journal(backend, 4)
        with patch.object(handoff, "wait_for", side_effect=RuntimeError("unproved")):
            with self.assertRaisesRegex(RuntimeError, "unproved"):
                handoff.execute("failover", backend, journal)
        self.assertEqual(backend.calls, [])
        self.assertEqual(len(journal.entries), 4)

    def test_changed_identity_or_process_refuses_before_dispatch(self):
        for change in ("identity", "run_id"):
            backend = Backend()
            journal = Journal(backend)
            if change == "identity":
                backend.identity_value = {"changed": True}
            else:
                backend.values["destination"]["run_id"] = "f" * 40
            with self.assertRaises(RuntimeError):
                handoff.execute("failover", backend, journal)
            self.assertEqual(backend.calls, [])
            self.assertEqual(len(journal.entries), 3)

    def test_bad_persistence_offset_peer_or_role_cannot_pass(self):
        for key, value in (("aof_last_write_status", "err"), ("aof_enabled", "0"),
                           ("aof_rewrite_in_progress", "1"), ("slave_repl_offset", "9"),
                           ("master_host", "10.0.1.3"), ("master_link_status", "down"), ("role", "master")):
            backend = Backend()
            original = plan(backend)
            backend.values["destination"][key] = value
            self.assertFalse(handoff.observe(backend, original))
        backend = Backend()
        original = plan(backend)
        backend.values["source"]["slave0"] = "ip=10.0.1.3,port=6379,state=online,offset=10,lag=0"
        self.assertFalse(handoff.observe(backend, original))

    def test_first_backlog_history_can_rotate_but_accepted_history_cannot(self):
        backend = Backend()
        original = plan(backend)
        backend.values["source"]["master_replid"] = "e" * 40
        backend.values["destination"]["master_replid"] = "e" * 40
        self.assertEqual(handoff.observe(backend, original)["primary_replid"], "e" * 40)
        journal = Journal(Backend())
        with self.assertRaisesRegex(RuntimeError, "history changed"):
            handoff.execute("failover", backend, journal)
        self.assertEqual(backend.calls, [])

    def test_discontinuous_promotion_history_is_not_acceptance(self):
        backend = Backend()
        original = plan(backend)
        backend.cli("source", "FAILOVER")
        backend.values["destination"]["master_replid2"] = "f" * 40
        with self.assertRaisesRegex(RuntimeError, "history discontinuity"):
            handoff.observe(backend, original, True, {"replid": "a" * 40, "offset": 10})

    def test_existing_replication_intent_observes_without_reconfiguration(self):
        backend = Backend()
        journal = Journal(backend, 2)
        result = handoff.execute("replicate", backend, journal)
        self.assertEqual(result[-1]["step"], "replica-accepted")
        self.assertEqual(backend.calls, [])

    def test_stale_append_preserves_original_intent(self):
        backend = Backend()
        journal = Journal(backend)
        with self.assertRaises(RuntimeError):
            handoff.append(journal.entries[:1], "replica-intent", {}, journal)
        self.assertEqual(len(journal.entries), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
