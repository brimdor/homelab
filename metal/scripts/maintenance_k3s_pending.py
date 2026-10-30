"""Read-only drain observations; pending replacements never prove application health."""

import json
from pathlib import Path
import subprocess

from maintenance_coordination import require
from maintenance_node_drain import hashed
import maintenance_production_node as shared


def pending_rook_rollout(api, item, owner):
    """A one-replica Rook rollout may have two unstarted, target-pinned Pods."""
    meta, spec = item['metadata'], item['spec']
    node = owner['node']
    if (owner.get('component') != 'k3s' or owner.get('phase') != 'OWNED_KURED_ONLY' or
            item['kind'] != 'Deployment' or meta['namespace'] != 'rook-ceph' or
            meta['name'] != 'rook-ceph-crashcollector-' + node or spec.get('replicas', 1) != 1):
        return False
    owners = [o for o in meta.get('ownerReferences', []) if o.get('controller')]
    if (len(owners) != 1 or owners[0].get('kind') != 'CephCluster' or
            owners[0].get('uid') != '901ad331-70b6-40cf-8654-2c6ed97a06b2' or
            spec.get('strategy') != {'type': 'RollingUpdate', 'rollingUpdate': {
                'maxSurge': '25%', 'maxUnavailable': '25%'}}):
        return False
    pods = api.call('get', 'pods', '-n', meta['namespace'], '-o', 'json')['items']
    labels = spec['selector'].get('matchLabels', {})
    pods = [p for p in pods if labels and all(p['metadata'].get('labels', {}).get(k) == v
                                            for k, v in labels.items())]
    if len(pods) != 2 or len({p['metadata']['uid'] for p in pods}) != 2:
        return False
    replicas = []
    for pod in pods:
        parents = [o for o in pod['metadata'].get('ownerReferences', []) if o.get('controller')]
        if (len(parents) != 1 or parents[0].get('kind') != 'ReplicaSet' or
                not any(c.get('type') == 'PodScheduled' and c.get('status') == 'False' and
                        c.get('reason') == 'Unschedulable' for c in pod['status'].get('conditions', []))):
            return False
        replicas.append(parents[0]['uid'])

        class OnePod:
            def call(self, *argv):
                return {'items': [pod]} if argv[:2] == ('get', 'pods') else api.call(*argv)

        if not shared.pending_on_maintained_node(OnePod(), item, node):
            return False
    return len(set(replicas)) == 2


def pending_versa_replacement(api, owner, ref):
    """Accept only this original owner's exact, never-started Versa replacement."""
    path = Path('metal/maintenance/k3s-cyndaquil-pending-versa.json')
    raw = path.read_bytes()
    require(raw == subprocess.check_output(['git', 'show', 'HEAD:' + str(path)]),
            'unpublished pending replacement profile')
    profile = json.loads(raw)
    require(profile['version'] == 1 and owner == profile['owner'] and ref == profile['ref'],
            'unreviewed pending replacement owner or original Pod')
    node = api.call('get', 'node', owner['node'], '-o', 'json')
    require(node['metadata']['uid'] == owner['node_uid'] and node['spec'].get('unschedulable') is True and
            not node['metadata'].get('deletionTimestamp'), 'replacement target is not owned and cordoned')
    deployment = api.call('get', 'deployment', 'versa', '-n', 'versa', '-o', 'json')
    meta, status = deployment['metadata'], deployment.get('status', {})
    require(meta['uid'] == profile['deployment_uid'] and meta['generation'] == profile['generation'] and
            not meta.get('deletionTimestamp') and deployment['spec'].get('replicas', 1) == 1 and
            status.get('observedGeneration') == meta['generation'] and
            hashed(deployment['spec']['template']) == profile['template_sha256'] and
            shared.pending_on_maintained_node(api, deployment, owner['node']),
            'replacement is not the unchanged pinned deployment')
    pods = api.call('get', 'pods', '-n', 'versa', '-o', 'json')['items']
    require(len(pods) == 1, 'replacement Pod membership differs')
    pod = pods[0]
    parents = [o for o in pod['metadata'].get('ownerReferences', []) if o.get('controller')]
    require(pod['metadata']['uid'] == profile['replacement_uid'] and
            pod['metadata']['creationTimestamp'] == profile['replacement_created'] and
            pod['metadata']['uid'] != ref['uid'] and len(parents) == 1 and
            parents[0] == ref['controller'] and
            {c['name']: c['image'] for c in pod['spec']['containers']} == profile['images'],
            'pending replacement identity, controller or artifact differs')
    claims = [v['persistentVolumeClaim']['claimName'] for v in pod['spec'].get('volumes', [])
              if 'persistentVolumeClaim' in v]
    require(claims == [b['claim'] for b in profile['bindings']], 'replacement persistence changed')
    for binding in profile['bindings']:
        claim = api.call('get', 'pvc', binding['claim'], '-n', 'versa', '-o', 'json')
        volume = api.call('get', 'pv', binding['volume'], '-o', 'json')
        require(claim['metadata']['uid'] == binding['claim_uid'] and
                claim['status']['phase'] == 'Bound' and claim['spec']['volumeName'] == binding['volume'] and
                volume['metadata']['uid'] == binding['volume_uid'] and
                volume['spec']['claimRef']['uid'] == binding['claim_uid'] and
                not claim['metadata'].get('deletionTimestamp') and
                not volume['metadata'].get('deletionTimestamp'), 'replacement storage binding changed')
    app = api.call('get', 'application', 'versa', '-n', 'argocd', '-o', 'json')
    require(app['metadata']['uid'] == profile['application_uid'] and
            not app['metadata'].get('deletionTimestamp') and app['status']['sync']['status'] == 'Synced' and
            subprocess.check_output(['git', 'diff', profile['configuration_commit'], 'HEAD', '--',
                                     'apps/versa']) == b'', 'Versa desired state changed')
    digest = profile['images']['web'].rsplit('@sha256:', 1)[-1]
    require(len(digest) == 64 and all(c in '0123456789abcdef' for c in digest), 'unbound artifact')
    proof = {'original': ref, 'replacement_uid': pod['metadata']['uid'], 'template': profile['template_sha256'],
             'bindings': profile['bindings'], 'unstarted_pinned_replacement': True}
    return {'kind': 'verified-controller-replacement', 'pod_uid': ref['uid'],
            'controller_uid': ref['controller']['uid'], 'replacement_uid': pod['metadata']['uid'],
            'application_uid': profile['application_uid'],
            'configuration_commit': profile['configuration_commit'], 'artifact_sha256': digest,
            'acceptance_sha256': hashed(proof)}
