"""Check fleet ownership cleanup and the actual generated native programs."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fedora_release_upgrade_qualification as upgrade
import maintenance_fedora_endpoint_qualification as fleet
from maintenance_fedora_endpoint import endpoint


class NativeFleet(unittest.TestCase):
    def test_refuse_foreign_revision_and_reused_owned_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for revision in ('',None,'main','a'*39,'g'*40):
                with self.subTest(revision=revision), self.assertRaises(RuntimeError):
                    fleet.Qualification(SimpleNamespace(work_dir=root,revision=revision))
            fixture=fleet.Qualification(SimpleNamespace(work_dir=root,revision='a'*40))
            with self.assertRaises(FileExistsError):
                fleet.Qualification(SimpleNamespace(work_dir=root,revision='a'*40))
            fixture.endpoints=[Mock()]
            with self.assertRaisesRegex(RuntimeError,'already prepared'):fixture.prepare()

    def test_cleanup_attempts_every_exact_owner_and_preserves_failures(self):
        fixture=object.__new__(fleet.Qualification)
        fixture.endpoints=[Mock(),Mock(),Mock()];fixture.hub=Mock()
        fixture.endpoints[1].cleanup.side_effect=RuntimeError('owned VM shutdown failed')
        fixture.hub.stop.side_effect=RuntimeError('owned hub stop failed')
        with self.assertRaises(ExceptionGroup)as raised:fixture.cleanup()
        self.assertEqual([str(error)for error in raised.exception.exceptions],
                         ['owned VM shutdown failed','owned hub stop failed'])
        for node in fixture.endpoints:node.cleanup.assert_called_once_with()
        fixture.hub.stop.assert_called_once_with()
        fixture.endpoints=[];fixture.hub=None;fixture.cleanup()

    def test_owned_process_receipt_tracks_restart_without_other_processes(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture=object.__new__(fleet.Qualification);fixture.root=Path(temporary)
            fixture.hub=SimpleNamespace(child=SimpleNamespace(pid=11),argv=['owned-hub'])
            node=SimpleNamespace(child=SimpleNamespace(pid=12),disk=fixture.root/'disk.qcow2',qemu_argv=['owned-VM'],
                                 prepared_keys=lambda:{'host':'a'*64,'login':'b'*64})
            fixture.endpoints=[node];fixture.ownership()
            first=json.loads((fixture.root/'ownership.json').read_text())
            self.assertEqual(first,{'hub_pid':11,'hub_argv':['owned-hub'],'endpoints':[{'pid':12,'disk':str(node.disk),'argv':['owned-VM'],'prepared_public_keys':{'host':'a'*64,'login':'b'*64}}]})
            node.child=SimpleNamespace(pid=13);fixture.ownership()
            second=json.loads((fixture.root/'ownership.json').read_text())
            self.assertEqual(second['hub_pid'],first['hub_pid'])
            self.assertEqual(second['endpoints'][0]['pid'],13)
            self.assertEqual(second['endpoints'][0]['argv'],first['endpoints'][0]['argv'])

    def test_native_peer_and_exchange_programs_compile_with_exact_guest_header(self):
        fixture=object.__new__(fleet.Qualification);fixture.endpoints=[];programs=[]
        for index in range(3):
            record=endpoint(index,23000+index)
            def guest(body,hostname=record['hostname']):
                compile(upgrade.guest_source(hostname)+body,'<actual-native-endpoint>','exec')
                programs.append(body);return {'program_compiled':True}
            fixture.endpoints.append(SimpleNamespace(endpoint=record,guest=guest))
        for node in fixture.endpoints:fixture.peer(node)
        for sender in range(3):
            for receiver in range(3):
                if sender!=receiver:fixture.exchange(sender,receiver,'native-test')
        self.assertEqual(len(programs),9)
        self.assertTrue(all('qualification-peer' in body and 'NRestarts' in body for body in programs[:3]))
        self.assertTrue(all('except ConnectionRefusedError'not in body for body in programs[3:]))
        compile(fleet.SERVER,'<actual-native-framed-echo-server>','exec')


if __name__ == '__main__':unittest.main()
