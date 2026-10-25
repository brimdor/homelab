"""Guard host-interface isolation, ownership and failure cleanup; native I/O separate."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import maintenance_vm_network as network


class NetworkTests(unittest.TestCase):
    def test_foreign_ports_and_paths_refuse_before_any_child_or_log(self):
        for ports in ([1, 2], [1, 1, 2], [True, 2, 3], [0, 2, 3], [65536, 2, 3], ['1', 2, 3]):
            with self.subTest(ports=ports), self.assertRaises(RuntimeError):network.arguments('/installed/qemu', ports)
        with self.assertRaises(RuntimeError):network.arguments('qemu', [1, 2, 3])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);root.chmod(0o755)
            with self.assertRaisesRegex(RuntimeError, 'private owned'):network.Hub('/installed/qemu', [1, 2, 3], root/'log')
            root.chmod(0o700);(root/'link').symlink_to(root/'log')
            with self.assertRaisesRegex(RuntimeError, 'unsafe'):network.Hub('/installed/qemu', [1, 2, 3], root/'link')

    def test_existing_log_refuses_and_launch_failure_leaves_no_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);root.chmod(0o700);log = root/'log';log.write_bytes(b'preserve')
            hub = network.Hub('/installed/qemu', [1, 2, 3], log)
            with patch.object(network.subprocess, 'Popen') as launch:
                with self.assertRaises(FileExistsError):hub.start()
                launch.assert_not_called()
            self.assertEqual(log.read_bytes(), b'preserve');hub.stop()
            log.unlink()
            with patch.object(network.subprocess, 'Popen', side_effect=OSError('launch failed')):
                with self.assertRaises(OSError):hub.start()
            self.assertIsNone(hub.child);hub.stop()

    def test_no_interface_or_disk_arguments_and_no_duplicate_child_dispatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);root.chmod(0o700);hub = network.Hub('/installed/qemu', [10001, 10002, 10003], root/'log')
            self.assertFalse(any(part in hub.argv for part in ('-drive', '-device', '-nic', '-net', '-enable-kvm')))
            self.assertTrue(all('listen=127.0.0.1:' in value for value in hub.argv if value.startswith('socket,')))
            with patch.object(network.subprocess, 'Popen') as launch:
                launch.return_value.pid = 999999;launch.return_value.poll.return_value = 0
                hub.start()
                with self.assertRaisesRegex(RuntimeError, 'already started'):hub.start()
                with self.assertRaisesRegex(RuntimeError, 'exited'):hub.running()
                hub.stop();hub.stop();self.assertEqual(launch.call_count, 1)


if __name__ == '__main__':
    unittest.main()
