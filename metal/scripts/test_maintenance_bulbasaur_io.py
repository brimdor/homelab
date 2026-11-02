#!/usr/bin/env python3
"""Keep passive capture parsing fail-closed across native edge cases."""

import unittest
from unittest.mock import patch

import maintenance_bulbasaur_io as capture


class NativeTimingRecords(unittest.TestCase):
    def test_spaces_empty_process_and_unavailable_queue(self):
        row = capture.parse_event('23:59:59.999 worker name    123 sda FWS -1 4096 -1.000 2048.125')
        self.assertEqual((row['comm'], row['pid'], row['queue_ms'], row['service_ms']),
                         ('worker name', 123, -1, 2048.125))
        empty = capture.parse_event('00:00:00.001                  0 sda F 0 0 0.000 1.500')
        self.assertEqual(empty['comm'], '')
        self.assertEqual(empty['bytes'], 0)

    def test_unexpected_records_are_errors_not_dropped_observations(self):
        original = '12:34:56.789 k3s 99 sda W 2048 4096 0.125 0.500'
        for row in ('Error: packet too small', original.replace('sda', 'sdb'),
                    original.replace('99 sda', '-1 sda'), original.replace(' W ', ' w '),
                    original.replace('4096', '-4096'), original.replace('0.125', '-0.125'),
                    original.replace('0.500', '-1.000'), original.replace('0.125', 'nan'),
                    original.replace('0.500', 'inf'), original.replace('12:34:56', '25:34:56')):
            with self.subTest(row=row), self.assertRaises((RuntimeError, ValueError)):
                capture.parse_event(row)

    def test_loss_is_counted_without_accepting_other_stderr_as_loss(self):
        self.assertEqual(capture.lost_events('lost 481 events on CPU #2'), 481)
        self.assertEqual(capture.lost_events('lost 0 events on CPU #0'), 0)
        for line in ('failed to attach BPF programs: -1', 'lost -1 events on CPU #0',
                     'lost 1 events on CPU #0 extra'):
            self.assertIsNone(capture.lost_events(line))

    def test_wrong_host_refused_before_disk_or_package_access(self):
        with patch.object(capture.os, 'geteuid', return_value=0), \
                patch.object(capture.socket, 'gethostname', return_value='other'), \
                patch.object(capture, 'output') as command:
            with self.assertRaisesRegex(RuntimeError, 'wrong native host'):
                capture.identity()
            command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
