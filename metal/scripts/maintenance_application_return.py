"""Read-only acceptance of an evicted application's unchanged controller."""

from datetime import datetime
import hashlib
import json


def returned_pod(reference, pods, deployment, replica_set, baseline_time):
    """Verify every configured replica, then identify the unique replacement."""
    owner = next(o for o in reference['owners'] if o.get('controller'))
    matches = [p for p in pods if not p['metadata'].get('deletionTimestamp')
               and any(o.get('controller') and o['uid'] == owner['uid']
                       for o in p['metadata'].get('ownerReferences', []))]
    if owner['kind'] == 'StatefulSet':
        matches = [p for p in matches if p['metadata']['name'] == reference['name']]
    if reference.get('deployment'):
        expected = reference['deployment']
        assert deployment['metadata']['uid'] == expected['uid']
        assert deployment['metadata']['generation'] == expected['generation']
        encoded = json.dumps(deployment['spec']['template'], sort_keys=True, separators=(',', ':'))
        assert hashlib.sha256(encoded.encode()).hexdigest() == expected['template_sha256']
        assert replica_set['metadata']['uid'] == owner['uid']
        assert any(o.get('controller') and o['uid'] == expected['uid']
                   for o in replica_set['metadata'].get('ownerReferences', []))
        count = deployment['spec']['replicas']
        assert count > 0 and replica_set['spec']['replicas'] == count
        assert deployment['status']['observedGeneration'] == deployment['metadata']['generation']
        for key in ('replicas', 'readyReplicas', 'availableReplicas', 'updatedReplicas'):
            assert deployment['status'].get(key) == count
    else:
        count = 1
    assert len(matches) == count, 'configured application replica count changed'
    for pod in matches:
        assert pod['metadata']['uid'] != reference['uid'], 'original evicted Pod still present'
        assert pod['status']['phase'] == 'Running'
        statuses = pod['status'].get('containerStatuses', [])
        assert len(statuses) == len(pod['spec']['containers']) and all(s.get('ready') for s in statuses)
        assert {c['name']: c['image'] for c in pod['spec']['containers']} == {
            c['name']: c['image'] for c in reference['containers']}
        assert [v['persistentVolumeClaim']['claimName'] for v in pod['spec'].get('volumes', [])
                if 'persistentVolumeClaim' in v] == reference['claims']
    if len(matches) == 1:
        return matches[0]
    after = datetime.fromisoformat(baseline_time.replace('Z', '+00:00'))
    replacements = [p for p in matches if datetime.fromisoformat(
        p['metadata']['creationTimestamp'].replace('Z', '+00:00')) > after]
    assert len(replacements) == 1, 'evicted application replacement is ambiguous'
    return replacements[0]
