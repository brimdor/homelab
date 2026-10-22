"""Verify binary framing and complete semantic comparisons without private output."""

import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import valkey_data_fingerprint as values
import valkey_write_pause_qualification as pause


class FingerprintTests(unittest.TestCase):
    def test_binary_request_and_nested_response(self):
        self.assertEqual(values.request('GET', b'\0\xff\r\n'), b'*2\r\n$3\r\nGET\r\n$4\r\n\0\xff\r\n\r\n')
        self.assertEqual(values.response(io.BytesIO(b'*3\r\n$4\r\n\0\xff\r\n\r\n:-1\r\n$-1\r\n')),
                         [b'\0\xff\r\n', -1, None])

    def test_truncation_bad_framing_and_errors_are_redacted(self):
        for raw in (b'$9\r\nshort', b'$2\r\nabxx', b'*1\r\n', b':bad\r\n', b'$-2\r\n',
                    b'-ERR secret-key-and-value\r\n', b'+bad\n'):
            with self.subTest(raw=raw), self.assertRaises(RuntimeError) as caught:
                values.response(io.BytesIO(raw))
            self.assertNotIn('secret', str(caught.exception))

    def test_unordered_types_normalize_but_lists_scores_expiry_and_values_matter(self):
        digest = lambda v: values.canonical(values.typed(v))
        self.assertEqual(digest([b'hash', -1, [b'b', b'2', b'a', b'1']]), digest([b'hash', -1, [b'a', b'1', b'b', b'2']]))
        self.assertEqual(digest([b'set', -1, [b'b', b'a']]), digest([b'set', -1, [b'a', b'b']]))
        for first, second in (([b'list', -1, [b'a', b'b']], [b'list', -1, [b'b', b'a']]),
                              ([b'zset', -1, [b'a', b'1']], [b'zset', -1, [b'a', b'2']]),
                              ([b'string', -1, b'a'], [b'string', 123456, b'a']),
                              ([b'string', -1, b'a'], [b'string', -1, b'b'])):
            self.assertNotEqual(digest(first), digest(second))
        for invalid in ([b'none', -2, None], [b'stream', -1, []], [b'hash', -1, [b'a']]):
            with self.assertRaises(RuntimeError):
                digest(invalid)

    def test_lengths_prevent_ambiguous_value_boundaries(self):
        self.assertNotEqual(values.canonical([b'ab', b'c']), values.canonical([b'a', b'bc']))

    def test_native_pause_program_compiles_and_refuses_failed_result(self):
        def command(arguments):
            self.assertEqual(arguments[:4], ['nsenter', '--target', '123', '--net'])
            compile(arguments[-1], '<wrapper>', 'exec')
            # Compile the actual embedded native body as well as its wrapper.
            program = pause.PROGRAM + repr(pause.OWNER) + pause.FINISH
            compile(program, '<synthetic-pause>', 'exec')
            return SimpleNamespace(stdout=json.dumps({'accepted': False, 'failure_class': 'AssertionError'}).encode(), stderr=b'')
        with patch.object(pause.common, 'command', side_effect=command), self.assertRaises(RuntimeError):
            pause.qualify(['nsenter', '--target', '123', '--net', '--'], b'# synthetic observer', 'synthetic-key')


if __name__ == '__main__':
    unittest.main()
