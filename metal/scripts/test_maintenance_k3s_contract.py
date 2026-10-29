"""K3s component ownership cannot become an OS action or skip serial nodes."""

import copy
import unittest

import maintenance_coordination as coordination
import maintenance_hop_journal as journal
import maintenance_k3s_contract as contract
from test_maintenance_coordination import API


class K3sContractTests(unittest.TestCase):
    def test_etcd_35_bridge_is_mandatory_before_embedded_36(self):
        self.assertEqual(contract.VERSIONS[:3], ('v1.33.6+k3s1', 'v1.33.10+k3s1', 'v1.33.13+k3s2'))
        self.assertEqual(contract.ETCD[contract.VERSIONS[1]], '3.5.26')
        self.assertFalse(contract.reviewed(contract.VERSIONS[0], contract.VERSIONS[2]))

    def test_only_reviewed_adjacent_artifacts(self):
        for source in contract.VERSIONS:
            for target in contract.VERSIONS:
                allowed = contract.VERSIONS.index(target) == contract.VERSIONS.index(source) + 1
                self.assertEqual(contract.reviewed(source, target), allowed)
                self.assertEqual(coordination.reviewed_hop('fixture-a', source, target, 'k3s'), allowed)
                self.assertFalse(coordination.reviewed_hop('fixture-a', source, target))
        self.assertFalse(coordination.reviewed_hop('fixture-a', 39, 41, 'k3s'))
        self.assertFalse(coordination.reviewed_hop('fixture-a', 39, 41, 'unknown'))

    def test_component_owner_survives_resume_and_refuses_an_os_journal(self):
        api = API()
        owner = api.controller().acquire('fixture-a', *contract.VERSIONS[:2], 'a' * 40, component='k3s')
        self.assertEqual(api.controller().resume(owner['owner']), owner)
        self.assertEqual(journal.steps(owner), contract.STEPS)
        self.assertFalse(set(('offline_transaction', 'security_default', 'download_release')) & set(journal.steps(owner)))
        with self.assertRaises(RuntimeError):
            api.controller().acquire('fixture-b', 39, 41, 'b' * 40)
        self.assertEqual(api.writes, 1)
        self.assertEqual(api.controller().release(owner['owner'], lambda _: True), owner)
        self.assertEqual(api.ds['metadata']['annotations'], {'unrelated': 'preserve'})

    def test_versions_cannot_disguise_a_fedora_transition(self):
        for component in ('k3s', 'unknown'):
            api = API()
            with self.assertRaises(RuntimeError):
                api.controller().acquire('fixture-a', 39, 41, 'a' * 40, component=component)
            self.assertEqual(api.writes, 0)
        with self.assertRaises(RuntimeError):
            journal.steps({'component': 'k3s', 'source': 44, 'target': 44})

    def test_servers_then_workers_and_last_two_tainted_nodes(self):
        source, target = contract.VERSIONS[:2]
        nodes = [{'metadata': {'name': name, 'uid': name + '-uid'},
                  'status': {'nodeInfo': {'kubeletVersion': source}}} for name in contract.ORDER]
        for node in nodes:
            self.assertEqual(contract.next_node(nodes, source, target), node['metadata']['name'])
            wrong = copy.deepcopy(nodes)
            if node is not nodes[-1]:
                wrong[-1]['status']['nodeInfo']['kubeletVersion'] = target
                with self.assertRaises(RuntimeError):
                    contract.next_node(wrong, source, target)
            node['status']['nodeInfo']['kubeletVersion'] = target
        self.assertIsNone(contract.next_node(nodes, source, target))
        with self.assertRaises(RuntimeError):
            contract.next_node(nodes[:-1], source, target)


if __name__ == '__main__':
    unittest.main()
