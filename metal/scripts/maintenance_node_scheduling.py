"""Journal one exact Node scheduling patch; resume observes without replay."""

import copy

import maintenance_actor_hold as actors
import maintenance_coordination as coordination
import maintenance_hop_journal as hops
from maintenance_node_drain import hashed, name, private_json


class Scheduling:
    def __init__(self, journal, api):
        self.journal, self.api = journal, api

    def snapshot(self, owner, node=None):
        if node is None:
            node = self.api.call('get', 'node', name(owner['node']), '-o', 'json')
        meta, spec = node['metadata'], node['spec']
        value = spec.get('unschedulable', False)
        actors.require(node.get('apiVersion') == 'v1' and node.get('kind') == 'Node' and
                       meta['name'] == owner['node'] and meta['uid'] == owner['node_uid'] and
                       not meta.get('deletionTimestamp') and
                       isinstance(meta.get('resourceVersion'), str) and meta['resourceVersion'] and
                       type(value) is bool, 'scheduling Node identity or state differs')
        return {'node': meta['name'], 'uid': meta['uid'],
                'resource_version': meta['resourceVersion'], 'unschedulable': value}

    @staticmethod
    def validate(plan, owner):
        actors.require(isinstance(plan, dict) and set(plan) == {
            'step', 'node', 'uid', 'resource_version', 'from_unschedulable',
            'to_unschedulable', 'original_cordon'}, 'invalid scheduling plan shape')
        actors.require(plan['step'] in ('cordon', 'restore_scheduling') and
                       plan['node'] == owner['node'] and plan['uid'] == owner['node_uid'] and
                       isinstance(plan['resource_version'], str) and plan['resource_version'] and
                       type(plan['from_unschedulable']) is bool and
                       type(plan['to_unschedulable']) is bool and
                       plan['from_unschedulable'] is (plan['step'] == 'restore_scheduling') and
                       plan['to_unschedulable'] is (plan['step'] == 'cordon'),
                       'unreviewed scheduling transition')
        original = plan['original_cordon']
        if plan['step'] == 'cordon':
            actors.require(original is None, 'cordon plan has foreign original state')
        else:
            actors.require(isinstance(original, dict) and original.get('step') == 'cordon',
                           'restoration lacks original cordon plan')
            Scheduling.validate(original, owner)

    def original(self, plan):
        if plan['step'] == 'restore_scheduling':
            first = private_json(self.journal.path / '00000001.json')
            actors.require(first.get('kind') == 'intent' and first.get('step') == 'cordon' and
                           first.get('inputs_sha256') == hashed(plan['original_cordon']),
                           'original cordon differs from durable first intent')

    def plan(self, step, original_cordon=None):
        with self.journal.hold.serialized():
            state = self.journal.read()
            node = self.snapshot(state['owners']['global'])
            plan = {'step': step, 'node': node['node'], 'uid': node['uid'],
                    'resource_version': node['resource_version'],
                    'from_unschedulable': node['unschedulable'],
                    'to_unschedulable': step == 'cordon',
                    'original_cordon': copy.deepcopy(original_cordon)}
            self.validate(plan, state['owners']['global'])
            self.original(plan)
            return plan

    def pending(self, state, plan):
        self.validate(plan, state['owners']['global'])
        self.original(plan)
        pending = state['pending']
        actors.require(pending is not None and pending['step'] == plan['step'],
                       'exact pending scheduling intent missing')
        intent = private_json(self.journal.path / (str(pending['sequence']).zfill(8) + '.json'))
        actors.require(intent['inputs_sha256'] == hashed(plan), 'pending scheduling plan differs')

    def dispatch(self, plan, reviewed_sha256, prerequisites_sha256, verify_prerequisites,
                 precheck_proof=None):
        plan = copy.deepcopy(plan)
        state = self.journal.inspect()
        self.validate(plan, state['owners']['global'])
        self.original(plan)
        actors.require(hashed(plan) == reviewed_sha256, 'scheduling plan differs from reviewed digest')
        if precheck_proof is None:
            pending = self.journal.begin(plan['step'], reviewed_sha256, prerequisites_sha256, verify_prerequisites)
        else:
            actors.require(isinstance(precheck_proof, dict) and set(precheck_proof) == {
                'owner', 'intent_sha256', 'failure_sha256'} and
                precheck_proof['owner'] == state['owners']['global']['owner'] and
                hops.checksum(precheck_proof['failure_sha256']) and
                plan['step'] == 'restore_scheduling' and state['pending'] is not None and
                state['pending']['sha256'] == precheck_proof['intent_sha256'],
                'reviewed scheduling pre-dispatch proof differs')
            pending = state
            self.pending(pending, plan)
        with self.journal.hold.serialized():
            actors.require(self.journal.read() == pending, 'scheduling intent changed before patch')
            self.journal.owners(idle=True)
            self.pending(pending, plan)
            actors.require(verify_prerequisites(plan['step'], prerequisites_sha256) is True,
                           'current scheduling prerequisites refused')
            actors.require(self.journal.read() == pending, 'scheduling state changed during verification')
            self.journal.owners(idle=True)
            before = self.snapshot(pending['owners']['global'])
            actors.require(before['unschedulable'] is plan['from_unschedulable'],
                           'reviewed scheduling Node changed before patch: ' +
                           coordination.encoded({'plan': plan, 'observed': before}))
            if precheck_proof is not None:
                # Only a proven pre-API exit permits this first dispatch; a sent request never does.
                marker = self.journal.hold.state / ('scheduling-first-dispatch-' + self.journal.token + '.json')
                actors.safe(marker)
                actors.require(not marker.exists(), 'scheduling first dispatch already armed; observe, never replay')
                actors.exclusive_file(marker, hops.canonical({
                    'proof': precheck_proof, 'plan_sha256': reviewed_sha256,
                    'prerequisites_sha256': prerequisites_sha256, 'before': before}), 0o600)
            # Fence the fresh read; kubelet status updates need not freeze after review.
            operations = [
                {'op': 'test', 'path': '/metadata/uid', 'value': plan['uid']},
                {'op': 'test', 'path': '/metadata/resourceVersion', 'value': before['resource_version']},
                {'op': 'add', 'path': '/spec/unschedulable', 'value': plan['to_unschedulable']},
            ]
            result = self.api.call('patch', 'node', name(plan['node']), '--type=json',
                                   '--patch', coordination.encoded(operations), '-o', 'json')
            after = self.snapshot(pending['owners']['global'], result)
            actors.require(after['unschedulable'] is plan['to_unschedulable'],
                           'scheduling patch outcome uncertain; observe, never replay')
            return {'accepted': False, 'pending': pending['pending'], 'before': before, 'observed': after}

    def observe(self, plan, prerequisites_sha256, verify_prerequisites):
        actors.require(hops.checksum(prerequisites_sha256), 'invalid scheduling prerequisite digest')
        plan = copy.deepcopy(plan)
        state = self.journal.inspect()
        self.pending(state, plan)
        owner = state['owners']['global']
        observed = self.snapshot(owner)
        if observed['unschedulable'] is not plan['to_unschedulable']:
            return {'accepted': False, 'pending': state['pending'], 'observed': observed}
        receipt = {'version': 1, 'step': plan['step'], 'inputs_sha256': hashed(plan),
                   'node': observed, 'prerequisites_sha256': prerequisites_sha256}
        def verify(step, digest):
            return (step == plan['step'] and digest == hashed(receipt) and
                    verify_prerequisites(step, prerequisites_sha256) is True and
                    self.snapshot(owner)['unschedulable'] is plan['to_unschedulable'])
        accepted = self.journal.accept(state['pending']['sha256'], hashed(receipt), verify)
        return {'accepted': True, 'receipt': receipt, 'journal': accepted}
