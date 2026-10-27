"""Observe the exact owner-approved Versa Canary replacement; never evict it."""

from maintenance_coordination import require
from maintenance_node_drain import hashed


REF = {
    'controller': {'apiVersion': 'apps/v1', 'blockOwnerDeletion': True, 'controller': True,
                   'kind': 'ReplicaSet', 'name': 'versa-canary-5764dd5584',
                   'uid': '3fd1a618-42c8-4cd4-abe3-3a6cf129543d'},
    'keep': False, 'name': 'versa-canary-5764dd5584-cpz6x', 'namespace': 'versa-canary',
    'spec_sha256': '42c841d0b3e0b1e7b3b3ab59445371d9f53e7ee37076662a489eba102244fe8a',
    'uid': 'f733c461-2555-45a9-be53-f4841451c059',
}
DEPLOYMENT = '72b69cae-fea1-4b99-ae0c-c515851cfac0'
REPLICA = 'e5342b06-6ffe-4b84-97d5-011e74c40de7'
POD = 'a64b0886-fb7e-4e1b-b9f1-185e759525de'
APPLICATION = '9090e6f9-484a-4e97-b4cf-d3bf15abf67d'
TEMPLATE_SHA256 = '92307b8f0e1555a430ac80fd82917e32a4db98428227ecf4df3506d00e3a2ace'
DIGEST = 'sha256:a2b42b994c1e2a65373cdcdda7556a6a801c517c4bd56d3693f89f4c073be33d'
CONFIGURATION = '9986c472c802f68f058897c7db1e45b5706647a7'


def observe(api, ref):
    require(ref == REF, 'unreviewed relocated drain target')
    namespace = REF['namespace']
    app = api.call('get', 'application', namespace, '-n', 'argocd', '-o', 'json')
    require(app['metadata']['uid'] == APPLICATION and not app['metadata'].get('deletionTimestamp') and
            app['status']['sync']['status'] == 'Synced' and app['status']['health']['status'] == 'Healthy' and
            app['status']['operationState']['phase'] == 'Succeeded', 'relocated application is not healthy')
    deployment = api.call('get', 'deployment', namespace, '-n', namespace, '-o', 'json')
    meta, status = deployment['metadata'], deployment['status']
    require(meta['uid'] == DEPLOYMENT and meta['generation'] == 132 and not meta.get('deletionTimestamp') and
            status.get('observedGeneration') == 132 and status.get('readyReplicas') == 1 and
            status.get('updatedReplicas') == 1 and deployment['spec']['replicas'] == 1 and
            hashed(deployment['spec']['template']) == TEMPLATE_SHA256, 'approved relocation template differs')
    for name, uid, replicas in ((REF['controller']['name'], REF['controller']['uid'], 0),
                               ('versa-canary-5c57fb798b', REPLICA, 1)):
        replica = api.call('get', 'replicaset', name, '-n', namespace, '-o', 'json')
        owners = [o for o in replica['metadata'].get('ownerReferences', []) if o.get('controller')]
        require(replica['metadata']['uid'] == uid and not replica['metadata'].get('deletionTimestamp') and
                replica['spec']['replicas'] == replicas and len(owners) == 1 and
                owners[0]['kind'] == 'Deployment' and owners[0]['uid'] == DEPLOYMENT,
                'relocation ReplicaSet identity or ownership differs')
    pods = api.call('get', 'pods', '-n', namespace, '-o', 'json')['items']
    require(len(pods) == 1, 'relocation must have exactly one surviving Pod')
    pod = pods[0]
    owners = [o for o in pod['metadata'].get('ownerReferences', []) if o.get('controller')]
    require(pod['metadata']['uid'] == POD and not pod['metadata'].get('deletionTimestamp') and
            pod['spec']['nodeName'] == 'charmander' and pod['status']['phase'] == 'Running' and
            len(owners) == 1 and owners[0]['kind'] == 'ReplicaSet' and owners[0]['uid'] == REPLICA,
            'relocation replacement Pod identity differs')
    states = pod['status'].get('initContainerStatuses', []) + pod['status'].get('containerStatuses', [])
    require(len(states) == 3 and {c['name'] for c in states} == {'migrate', 'web', 'worker'} and
            all(c['restartCount'] == 0 and c['imageID'].endswith('@' + DIGEST) and
                (c['state'].get('terminated', {}).get('exitCode') == 0 if c['name'] == 'migrate'
                 else c['ready'] and 'running' in c['state']) for c in states),
            'original migration or runtime acceptance differs')
    warnings = api.call('get', 'events', '-n', namespace, '--field-selector',
                        'involvedObject.uid=' + POD + ',type=Warning', '-o', 'json')['items']
    require(not warnings, 'relocation has current warning events')
    program = ('const checks={};for(const path of ["/healthz","/readyz"]){'
               'const r=await fetch(`http://${process.env.HOSTNAME}:3000${path}`);'
               'if(r.status!==200)throw Error(path+" "+r.status);checks[path]=r.status;}'
               'console.log(JSON.stringify(checks));')
    health = api.call('exec', '-n', namespace, pod['metadata']['name'], '-c', 'web', '--',
                      'node', '--input-type=module', '-e', program)
    require(health == {'/healthz': 200, '/readyz': 200}, 'relocation behavior differs')
    return {'kind': 'verified-controller-replacement', 'pod_uid': REF['uid'],
            'controller_uid': REF['controller']['uid'], 'replacement_uid': POD,
            'application_uid': APPLICATION, 'configuration_commit': CONFIGURATION,
            'artifact_sha256': DIGEST.removeprefix('sha256:'),
            'acceptance_sha256': hashed({'ref': REF, 'template': TEMPLATE_SHA256, 'pod': POD, 'health': health})}
