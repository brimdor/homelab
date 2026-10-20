#!/usr/bin/env python3
"""In-memory checks; never call a host, Docker, Kubernetes or a real store."""

import unittest
from unittest.mock import patch
import urllib.parse

import loki_frozen_query as subject


class FrozenQueryContract(unittest.TestCase):
    def test_source_accounting_refuses_new_writers_or_refusal_classes(self):
        metrics = ('loki_ingester_memory_chunks 0\n'
                   'loki_distributor_lines_received_total{user="fake"} 7373410\n'
                   'loki_discarded_samples_total{reason="rate_limited",user="fake"} 5249\n'
                   'loki_discarded_samples_total{reason="line_too_long",user="fake"} 1\n')
        with patch.object(subject, "command", return_value=metrics.encode()):
            self.assertEqual(len(subject.source_counters(123)), 4)
        for changed in (metrics.replace("7373410", "7373411"),
                        metrics.replace("chunks 0", "chunks 1"),
                        metrics.replace("rate_limited", "unexpected"),
                        metrics.replace("5249", "NaN")):
            with patch.object(subject, "command", return_value=changed.encode()):
                with self.assertRaises(RuntimeError):
                    subject.source_counters(123)

    def test_same_frozen_bounds_as_transfer(self):
        for end, _ in subject.RANGES.values():
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(subject.query_path(end)).query)
            duration = (end - subject.START) // 10**9 + 2
            self.assertEqual(query, {"query": ['sum(count_over_time({job=~".+"}[' + str(duration) + "s]))"],
                                     "time": [str(end)]})

    def test_count_mismatch_is_observed_without_fabricating_equality(self):
        value = {"status": "success", "data": {"resultType": "vector", "result": [{"value": [1, "7368141"]}],
                 "stats": {"summary": {"splits": 13, "shards": 133},
                           "querier": {"store": {"totalChunksRef": 1523}},
                           "ingester": {"store": {"totalChunksRef": 314}}}}}
        self.assertEqual(subject.summarize(value)["count"], 7368141)
        for invalid in ("NaN", "-1", "1.2", "inf", 42):
            value["data"]["result"][0]["value"][1] = invalid
            with self.assertRaises(RuntimeError):
                subject.summarize(value)


if __name__ == "__main__":
    unittest.main()
