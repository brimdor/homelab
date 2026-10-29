#!/usr/bin/env python3
"""Require exact native trace pairs; never hide loss or incomplete observations."""

import unittest

import builder_readiness_trace as subject


def event(edge, call='fsync', timestamp='100.000000', payload=None, tid=7894):
    if payload is None:
        payload = '(fd: b)' if edge == 'enter' else ' -> 0x0'
    return f' node-{tid} [002] .... {timestamp}: sys_{call}{payload}'


class TraceSamples(unittest.TestCase):
    def samples(self):
        return subject.Samples({7894, 7895}, {11: {'store': 'recovery'}})

    def test_exact_pair_duration_error_and_descriptor_attribution(self):
        value = self.samples()
        value.add(event('enter'))
        value.add(event('exit', timestamp='100.500123'))
        value.add(event('enter', 'fdatasync', '101.000000', '(fd: c)'))
        value.add(event('exit', 'fdatasync', '106.000000', ' -> 0xfffffffffffffffB'))
        result = value.result()
        self.assertEqual(result['completed'], 2)
        recovery = result['groups']['recovery/fsync']
        self.assertEqual(recovery['max_ns'], 500123000)
        self.assertEqual(recovery['at_least_500ms'], 1)
        self.assertEqual(recovery['at_least_5s'], 0)
        self.assertEqual(recovery['errors'], 0)
        other = result['groups']['unattributed/fdatasync']
        self.assertEqual(other['at_least_5s'], 1)
        self.assertEqual(other['errors'], 1)

    def test_window_edges_remain_incomplete_and_internal_orphan_refused(self):
        value = self.samples()
        value.add(event('exit'))
        value.add(event('enter', tid=7895))
        self.assertEqual(value.result(), {'completed': 0, 'groups': {},
                                         'window_edge_exits': 1, 'window_edge_pending': 1})
        with self.assertRaises(RuntimeError):
            value.add(event('exit'))

    def test_native_kernel_format_preserves_duration_descriptor_and_errors(self):
        value = self.samples()
        value.add(' node-7894 [002] .... 100.000000001: sys_enter_fsync: fd: 0x0000000b')
        value.add(' node-7894 [002] .... 105.000000001: sys_exit_fsync: 0x0')
        value.add(' node-7895 [002] .... 106.000000001: sys_enter_fdatasync: fd: 0x0000000c')
        value.add(' node-7895 [002] .... 106.000000002: sys_exit_fdatasync: 0xfffffffffffffffB')
        result = value.result()
        self.assertEqual(result['groups']['recovery/fsync']['max_ns'], 5000000000)
        self.assertEqual(result['groups']['recovery/fsync']['at_least_5s'], 1)
        self.assertEqual(result['groups']['unattributed/fdatasync']['errors'], 1)

    def test_rejected_line_diagnostic_excludes_names_and_numbers(self):
        with self.assertRaises(RuntimeError) as caught:
            self.samples().add(' private-name-12345 [002] .... 100.000000: unknown-secret: 0xabc')
        self.assertNotIn('private', str(caught.exception))
        self.assertNotIn('secret', str(caught.exception))
        self.assertNotIn('12345', str(caught.exception))

    def test_loss_foreign_pid_format_duplicate_and_clock_refusals(self):
        for line in ('CPU:2 [LOST 10 EVENTS]', event('enter', tid=200),
                     event('enter', payload='(fd: 0xb)'), event('exit', payload='ret=0'),
                     ' node-200 [002] .... 100.000000: sys_enter_fsync: fd: 0x0000000b',
                     ' node-7894 [002] .... 100.000000: sys_enter_fsync: 0x0',
                     ' node-7894 [002] .... 100.000000: sys_exit_fsync: fd: 0x0000000b',
                     ' node-7894 [002] .... 100.000000: sys_enter_fsync: fd: 0000000b',
                     ' node-7894 [002] .... 100.000000: sys_exit_fsync: 0x0 extra'):
            with self.assertRaises(RuntimeError):
                self.samples().add(line)
        for bad in (event('enter'), event('exit', timestamp='99.999999'), event('exit', 'fdatasync')):
            value = self.samples()
            value.add(event('enter'))
            with self.assertRaises(RuntimeError):
                value.add(bad)


if __name__ == '__main__':
    unittest.main()
