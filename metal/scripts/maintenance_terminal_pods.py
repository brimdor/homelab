#!/usr/bin/env python3
"""Remove published terminal Deployment Pod objects after their replacements recover."""

import argparse
import json
from pathlib import Path

from maintenance_coordination import Kubectl, encoded, require


PROFILE = Path(__file__).resolve().parents[1] / 'maintenance/pikachu-terminal-evictions.json'


def owned(resource, kind, reference):
    return any(o.get('controller') is True and o.get('kind') == kind and
               o.get('name') == reference['name'] and o.get('uid') == reference['uid']
               for o in resource['metadata'].get('ownerReferences', []))


def healthy(resource):
    statuses = resource['status'].get('containerStatuses', [])
    return (not resource['metadata'].get('deletionTimestamp') and
            resource['status'].get('phase') == 'Running' and bool(statuses) and
            all(c.get('ready') and c.get('restartCount') == 0 for c in statuses) and
            any(c['type'] == 'Ready' and c['status'] == 'True'
                for c in resource['status'].get('conditions', [])))


def terminal(resource, node, reference, controller):
    statuses = (resource['status'].get('containerStatuses', []) +
                resource['status'].get('initContainerStatuses', []))
    phase = reference['phase']
    disposition = (phase == 'Failed' and reference['reason'] == 'Evicted')
    if phase == 'Succeeded' and reference['reason'] is None:
        mains = resource['status'].get('containerStatuses', [])
        disposition = (resource['spec'].get('restartPolicy') == 'Always' and bool(mains) and
                       {c['name'] for c in mains} == {c['name'] for c in resource['spec']['containers']} and
                       all(c.get('state', {}).get('terminated', {}).get('exitCode') == 0 for c in statuses))
    return (resource['metadata']['uid'] == reference['uid'] and
            resource['metadata']['name'] == reference['name'] and
            not resource['metadata'].get('deletionTimestamp') and
            resource['spec'].get('nodeName') == node and
            disposition and resource['status'].get('phase') == phase and
            resource['status'].get('reason') == reference['reason'] and
            owned(resource, 'ReplicaSet', controller) and
            all('terminated' in c.get('state', {}) for c in statuses))


def inspect(api, profile):
    require(profile.get('schema_version') == 2 and profile['issue'] == 103 and
            profile['node'] == 'pikachu', 'unreviewed cleanup scope')
    node = api.call('get', 'node', profile['node'], '-o', 'json')
    conditions = {c['type']: c['status'] for c in node['status']['conditions']}
    require(not node['spec'].get('unschedulable') and conditions.get('Ready') == 'True' and
            all(conditions.get(k) == 'False' for k in ('DiskPressure', 'MemoryPressure', 'PIDPressure')),
            'node pressure or readiness has not recovered')
    targets, absent = {}, []
    for application in profile['applications']:
        namespace = application['namespace']
        deployment = api.call('get', 'deployment', application['deployment']['name'], '-n', namespace, '-o', 'json')
        status = deployment['status']
        require(deployment['metadata']['uid'] == application['deployment']['uid'] and
                not deployment['metadata'].get('deletionTimestamp') and deployment['spec']['replicas'] == 1 and
                status.get('observedGeneration') == deployment['metadata']['generation'] and
                all(status.get(k) == 1 for k in ('replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas')) and
                status.get('terminatingReplicas', 0) == 0, 'replacement deployment not stable')
        replicaset = api.call('get', 'replicaset', application['replicaset']['name'], '-n', namespace, '-o', 'json')
        require(replicaset['metadata']['uid'] == application['replicaset']['uid'] and
                owned(replicaset, 'Deployment', application['deployment']), 'controller ownership changed')
        pods = api.call('get', 'pods', '-n', namespace, '-o', 'json')['items']
        replacement = [p for p in pods if p['metadata']['name'] == application['replacement']['name']]
        require(len(replacement) == 1 and replacement[0]['metadata']['uid'] == application['replacement']['uid'] and
                owned(replacement[0], 'ReplicaSet', application['replicaset']) and healthy(replacement[0]),
                'published replacement not healthy or changed')
        for reference in application['targets']:
            found = [p for p in pods if p['metadata']['name'] == reference['name']]
            if not found:
                absent.append(reference['uid'])
                continue
            require(len(found) == 1 and terminal(found[0], profile['node'], reference, application['replicaset']),
                    'target is no longer the exact terminal eviction')
            targets[reference['uid']] = (namespace, found[0])
    return targets, absent


def remove(api, profile, uid):
    matches = [(application, reference) for application in profile['applications']
               for reference in application['targets'] if reference['uid'] == uid]
    require(len(matches) == 1, 'one unique published target required')
    application, reference = matches[0]
    scoped = dict(profile, applications=[dict(application, targets=[reference])])
    targets, _ = inspect(api, scoped)
    require(uid in targets, 'target absent or unpublished; do not replay an uncertain deletion')
    namespace, pod = targets[uid]
    options = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'preconditions': {
        'uid': uid, 'resourceVersion': pod['metadata']['resourceVersion']}}
    return api.call('delete', '--raw', '/api/v1/namespaces/' + namespace + '/pods/' + pod['metadata']['name'],
                    '-f', '-', data=encoded(options).encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubectl', required=True)
    parser.add_argument('--operation', choices=('inspect', 'remove'), default='inspect')
    parser.add_argument('--uid')
    args = parser.parse_args()
    api, profile = Kubectl(args.kubectl), json.loads(PROFILE.read_text())
    if args.operation == 'remove':
        require(bool(args.uid), 'one explicit published UID required')
        remove(api, profile, args.uid)
        print(json.dumps({'deletion_submitted': args.uid, 'absence_verification_required': True}))
    else:
        targets, absent = inspect(api, profile)
        print(json.dumps({'present_terminal_uids': list(targets), 'absent_uids': absent}))


if __name__ == '__main__':
    main()
