"""Exact existing ownership during the one server's journaled SOURCE cycle.

This read-only guard does not prove a native stop or authorize a service action.
Ordinary maintenance ownership continues to require every node and Kured ready.
"""

from maintenance_actor_hold import require
from maintenance_k3s_contract import ORDER
from maintenance_node_drain import hashed


def runtime(controller, pod):
    require(not pod['metadata'].get('deletionTimestamp') and pod['status']['phase'] == 'Running',
            'original Kured Pod is not running')
    controller.runtime(pod['spec'])
    states = pod['status'].get('containerStatuses', [])
    require(len(states) == 1 and states[0]['name'] == 'kured' and
            states[0].get('containerID') and states[0].get('imageID') and
            type(states[0].get('restartCount')) is int and states[0]['restartCount'] >= 0 and
            states[0].get('state', {}).get('running', {}).get('startedAt'),
            'original Kured process identity incomplete')
    state = states[0]
    return {key: state[key] for key in ('containerID', 'imageID', 'restartCount', 'state')}


def capture(controller, token):
    healthy = controller.observed()
    owner = controller.ownership(healthy, token)
    require(owner.get('component') == 'k3s' and owner['node'] in ('charmander', 'squirtle', 'bulbasaur') and
            (owner['source'], owner['target']) == ('v1.33.10+k3s1', 'v1.33.13+k3s2'),
            'unreviewed SOURCE cycle owner')
    ds, pods, nodes = controller.api.snapshot()
    require(ds == healthy and controller.ownership(ds, token) == owner, 'ownership changed during cycle capture')
    require(len(nodes) == 9 and {n['metadata']['name'] for n in nodes} == set(ORDER) and
            len(pods) == 9, 'cycle inventory differs')
    baseline = {'owner': owner, 'daemonset_uid': ds['metadata']['uid'],
                'generation': ds['metadata']['generation'], 'spec_sha256': hashed(ds['spec']),
                'nodes': {n['metadata']['name']: {'uid': n['metadata']['uid'],
                          'unschedulable': n.get('spec', {}).get('unschedulable', False)} for n in nodes},
                'pods': {p['metadata']['uid']: {'node': p['spec']['nodeName'], 'name': p['metadata']['name'],
                         'spec_sha256': hashed(p['spec']), 'runtime': runtime(controller, p)} for p in pods}}
    observe(controller, baseline)
    return baseline


def observe(controller, baseline):
    ds, pods, nodes = controller.api.snapshot();owner = baseline['owner'];target = owner['node']
    require(owner.get('component') == 'k3s' and target in ('charmander', 'squirtle', 'bulbasaur') and
            (owner['source'], owner['target']) == ('v1.33.10+k3s1', 'v1.33.13+k3s2') and
            controller.ownership(ds, owner['owner']) == owner, 'owned SOURCE cycle lock changed')
    meta, status = ds['metadata'], ds['status']
    owned_unknown = [n for n in nodes if n['metadata']['name'] == target and
                     any(c['type'] == 'Ready' and c['status'] == 'Unknown' for c in n['status']['conditions']) and
                     any(t.get('key') == 'node.kubernetes.io/unreachable' and t.get('effect') == 'NoSchedule'
                         for t in n.get('spec', {}).get('taints', []))]
    scheduling = tuple(status.get(k, 0) for k in
                       ('desiredNumberScheduled', 'currentNumberScheduled', 'updatedNumberScheduled', 'numberMisscheduled'))
    # A stopped kubelet can make its still-running original daemon ineligible for scheduling.
    scoped_scheduling = scheduling == (8, 8, 8, 1) and len(owned_unknown) == 1
    require(meta['uid'] == baseline['daemonset_uid'] == controller.uid and meta['name'] == 'kured' and
            meta['namespace'] == 'kured' and not meta.get('deletionTimestamp') and
            meta['generation'] == status.get('observedGeneration') == baseline['generation'] and
            hashed(ds['spec']) == baseline['spec_sha256'] and
            (scheduling == (9, 9, 9, 0) or scoped_scheduling) and
            all(status.get(k) in (8, 9) for k in ('numberReady', 'numberAvailable')) and
            (not scoped_scheduling or all(status.get(k) == 8 for k in ('numberReady', 'numberAvailable'))) and
            status.get('numberUnavailable', 0) in (0, 1),
            'Kured deployment changed during SOURCE cycle')
    require(len(nodes) == 9 and set(baseline['nodes']) == set(ORDER) and
            {n['metadata']['name']: n['metadata']['uid'] for n in nodes} ==
            {name: item['uid'] for name, item in baseline['nodes'].items()} == controller.nodes,
            'SOURCE cycle Node identities changed')
    for node in nodes:
        name = node['metadata']['name'];conditions = {c['type']: c['status'] for c in node['status']['conditions']}
        require(not node['metadata'].get('deletionTimestamp'), 'SOURCE cycle Node is deleting')
        if name == target:
            require(node.get('spec', {}).get('unschedulable') is True and
                    conditions.get('Ready') in ('True', 'Unknown') and
                    all(conditions.get(k) in ('False', 'Unknown') for k in ('MemoryPressure', 'DiskPressure', 'PIDPressure')),
                    'owned SOURCE cordon or heartbeat differs')
        else:
            require(conditions.get('Ready') == 'True' and
                    all(conditions.get(k) == 'False' for k in ('MemoryPressure', 'DiskPressure', 'PIDPressure')) and
                    node.get('spec', {}).get('unschedulable', False) == baseline['nodes'][name]['unschedulable'],
                    'another node changed during SOURCE cycle')
    require(len(pods) == 9 and len(baseline['pods']) == 9 and
            {p['metadata']['uid'] for p in pods} == set(baseline['pods']) and
            {p['spec']['nodeName'] for p in pods} == set(ORDER), 'original Kured Pod membership changed')
    for pod in pods:
        original = baseline['pods'][pod['metadata']['uid']]
        require(any(o.get('controller') is True and o.get('uid') == controller.uid for o in pod['metadata'].get('ownerReferences', [])) and
                pod['metadata']['name'] == original['name'] and pod['spec']['nodeName'] == original['node'] and
                hashed(pod['spec']) == original['spec_sha256'] and runtime(controller, pod) == original['runtime'],
                'original Kured process changed during SOURCE cycle')
        require(pod['spec']['nodeName'] == target or pod['status']['containerStatuses'][0].get('ready') is True,
                'another Kured container is unready')
    return True
