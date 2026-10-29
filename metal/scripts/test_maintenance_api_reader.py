"""Proxy startup readiness must precede the first API read."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import maintenance_api_reader as reader


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.runtime = tempfile.TemporaryDirectory()
        self.addCleanup(self.runtime.cleanup)
        os.chmod(self.runtime.name, 0o700)
        self.environment = patch.dict(os.environ, XDG_RUNTIME_DIR=self.runtime.name)
        self.environment.start(); self.addCleanup(self.environment.stop)

    def test_bound_socket_is_not_ready_until_connect_succeeds(self):
        process = Mock(); process.poll.return_value = None
        connection = Mock(); connection.connect.side_effect = [ConnectionRefusedError(), None]
        with patch.object(reader.subprocess, 'Popen', return_value=process), \
                patch.object(reader, 'Connection', return_value=connection), \
                patch.object(Path, 'exists', return_value=True), patch.object(reader.time, 'sleep'):
            api = reader.Reader('/managed/kubectl')
            self.assertEqual(connection.connect.call_count, 2)
            connection.close.assert_called_once()
            process.terminate.assert_not_called()
            directory = api.directory
            api.close()
        self.assertFalse(directory.exists())
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=10)

    def test_proxy_exit_after_refusal_cleans_connection_and_runtime(self):
        process = Mock(); process.poll.side_effect = [None, 1, 1]
        connection = Mock(); connection.connect.side_effect = ConnectionRefusedError()
        with patch.object(reader.subprocess, 'Popen', return_value=process), \
                patch.object(reader, 'Connection', return_value=connection), \
                patch.object(Path, 'exists', return_value=True), patch.object(reader.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'reader did not start'):
                reader.Reader('/managed/kubectl')
        self.assertEqual(connection.connect.call_count, 1)
        self.assertEqual(connection.close.call_count, 2)
        self.assertEqual(list(Path(self.runtime.name).iterdir()), [])
        process.terminate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
