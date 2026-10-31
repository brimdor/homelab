"""Owner-prioritized node completion must preserve every supported runtime prefix."""

import copy
import unittest

import maintenance_k3s_contract as contract
import maintenance_control_plane as control_plane


class CompletionOrderTests(unittest.TestCase):
    def nodes(self, versions=None):
        versions = versions or dict.fromkeys(contract.ORDER, contract.VERSIONS[2])
        return [{'metadata': {'name': name, 'uid': 'uid-' + name},
                 'status': {'nodeInfo': {'kubeletVersion': versions[name]}}}
                for name in contract.ORDER]

    def test_every_prefix_selects_only_next_hop_and_respects_version_skew(self):
        nodes = self.nodes()
        states = contract.completion_states()
        self.assertEqual(len(states), len(contract.COMPLETION_ORDER) + 1)
        for index, (node, source, target) in enumerate(contract.COMPLETION_ORDER):
            with self.subTest(index=index, node=node):
                self.assertEqual(contract.next_transition(nodes), (node, source, target))
                self.assertEqual(contract.next_node(nodes, source, target), node)
                self.assertTrue(contract.reviewed(source, target))
                actual = {n['metadata']['name']: n['status']['nodeInfo']['kubeletVersion'] for n in nodes}
                self.assertEqual(actual, states[index])
                servers = {n: actual[n] for n in contract.ORDER[:3]}
                control_plane.expected_versions(servers)
                minors = [int(v.split('.')[1]) for v in servers.values()]
                self.assertLessEqual(max(minors) - min(minors), 1)
                for worker in contract.ORDER[3:]:
                    minor = int(actual[worker].split('.')[1])
                    self.assertLessEqual(minor, min(minors))
                    self.assertGreaterEqual(minor, max(minors) - 3)
                next(n for n in nodes if n['metadata']['name'] == node)[
                    'status']['nodeInfo']['kubeletVersion'] = target
        self.assertIsNone(contract.next_transition(nodes))
        self.assertEqual({n['status']['nodeInfo']['kubeletVersion'] for n in nodes},
                         {contract.VERSIONS[-1]})

    def test_squirtle_finishes_first_then_sprigatito_before_other_workers(self):
        sequence = contract.COMPLETION_ORDER
        self.assertEqual(next(node for node, _, target in sequence if target == contract.VERSIONS[-1]),
                         'squirtle')
        workers = [step for step in sequence if step[0] not in contract.ORDER[:3]]
        expected = [(node, source, target) for node in contract.ORDER[3:]
                    for source, target in zip(contract.VERSIONS[2:], contract.VERSIONS[3:])]
        self.assertEqual(workers, expected)
        self.assertEqual(workers[0][0], 'sprigatito')
        self.assertLess([n for n, _, _ in workers].index('growlithe'),
                        [n for n, _, _ in workers].index('arcanine'))
        worker_start = next(i for i, step in enumerate(sequence) if step[0] == 'sprigatito')
        self.assertTrue(all(contract.completion_states()[worker_start][n] == contract.VERSIONS[-1]
                            for n in contract.ORDER[:3]))

    def test_skipped_reordered_or_foreign_state_is_refused(self):
        for node, target in (('squirtle', contract.VERSIONS[-1]),
                             ('sprigatito', contract.VERSIONS[3]),
                             ('bulbasaur', contract.VERSIONS[3])):
            nodes = self.nodes()
            next(n for n in nodes if n['metadata']['name'] == node)[
                'status']['nodeInfo']['kubeletVersion'] = target
            with self.subTest(node=node), self.assertRaises(RuntimeError):
                contract.next_transition(nodes)
        for mutate in (lambda n: n.pop(),
                       lambda n: n.append(copy.deepcopy(n[0])),
                       lambda n: n[0]['metadata'].update(uid=''),
                       lambda n: n[0]['metadata'].update(uid=n[1]['metadata']['uid'])):
            nodes = self.nodes(); mutate(nodes)
            with self.subTest(mutate=mutate), self.assertRaises(RuntimeError):
                contract.next_transition(nodes)

    def test_changed_server_order_or_two_minor_gap_is_refused(self):
        for versions in ({'charmander': contract.VERSIONS[4], 'squirtle': contract.VERSIONS[3],
                          'bulbasaur': contract.VERSIONS[3]},
                         {'charmander': contract.VERSIONS[3], 'squirtle': contract.VERSIONS[-1],
                          'bulbasaur': contract.VERSIONS[3]}):
            with self.subTest(versions=versions), self.assertRaises(RuntimeError):
                control_plane.expected_versions(versions)


if __name__ == '__main__':
    unittest.main()
