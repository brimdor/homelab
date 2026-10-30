"""Reviewed Issue 103 K3s artifact chain and serial production order."""

VERSIONS = (
    'v1.33.6+k3s1', 'v1.33.10+k3s1', 'v1.33.13+k3s2', 'v1.34.12+k3s1',
    'v1.35.9+k3s1', 'v1.36.5+k3s1',
)
SHA256 = dict(zip(VERSIONS, (
    '86945269160fdd1bbd06283ea5b3bafd6c0ec0d1df3ac68ad3686656632081a5',
    'cc435a91072e90680ccea689d4f491ac254ce62f658445a1ccfc2244fce667e1',
    '1572f0f23bd5a844bd405b71875877aacacc7ab79e279d3d73735654c37c7735',
    'ef1df26b26276c0f6d962391c94e12f9362d1f1e30ec7a7926e9ddb84b0d66ce',
    '897acb21cca57d477a211102251a6591450ce767344a9faaa121a1007ca9fa9a',
    'd73847bcd3c5fccef0115b372e2f9a91f3032dc84bbf71518a4617565294d313',
)))
# Keep the last reviewed etcd 3.5 K3s release before the embedded 3.6 transition.
ETCD = dict(zip(VERSIONS, ('3.5.21', '3.5.26', '3.6.14', '3.6.14', '3.6.14', '3.6.14')))
# Owner prioritized Sprigatito immediately after the active Bulbasaur transition.
ORDER = ('charmander', 'squirtle', 'bulbasaur', 'sprigatito', 'pikachu',
         'cyndaquil', 'totodile', 'growlithe', 'arcanine')
STEPS = ('cordon', 'drain', 'prepare_binary', 'activate_binary',
         'verify_infrastructure', 'restore_scheduling', 'accept_applications')


def reviewed(source, target):
    return (source, target) in tuple(zip(VERSIONS, VERSIONS[1:]))


def steps(owner):
    """The embedded etcd 3.6 boundary adds a server-only protected legacy check."""
    if not reviewed(owner['source'], owner['target']):
        raise RuntimeError('unreviewed K3s journal transition')
    if ((owner['source'], owner['target']) == VERSIONS[1:3] and
            owner['node'] in ('charmander', 'squirtle', 'bulbasaur')):
        return STEPS[:2] + ('check_legacy_etcd',) + STEPS[2:]
    return STEPS


def ceph_policy(cluster, stage):
    """Preserve the historical first-stage gate; later stages require retired prior keys."""
    if not reviewed(*stage):
        raise RuntimeError('unreviewed K3s Ceph stage')
    csi = cluster.get('status', {}).get('cephx', {}).get('csi', {})
    common = (cluster.get('status', {}).get('phase') == 'Ready' and
              csi.get('keyGeneration') == 1 and csi.get('keyType') == 'aes256k' and
              csi.get('keyCephVersion') == '20.2.4-0')
    if stage == VERSIONS[:2]:
        return common and csi.get('priorKeyCount') == 1
    return (common and csi.get('priorKeyCount', 0) == 0 and
            cluster.get('spec', {}).get('security', {}).get('cephx', {}).get('csi') ==
            {'keyRotationPolicy': 'KeyGeneration', 'keyGeneration': 1,
             'keepPriorKeyCountMax': 0, 'keyType': 'aes256k'} and
            cluster['spec']['security']['cephx'].get('allowedCiphers') == ['aes256k'])


def next_node(nodes, source, target):
    """Refuse skipped hosts, unreviewed versions and foreign inventory."""
    if not reviewed(source, target):
        raise RuntimeError('unreviewed K3s transition')
    by_name = {node['metadata']['name']: node for node in nodes}
    if len(nodes) != len(ORDER) or set(by_name) != set(ORDER):
        raise RuntimeError('K3s active inventory differs')
    remaining = []
    for name in ORDER:
        node = by_name[name]
        version = node['status']['nodeInfo']['kubeletVersion']
        if node['metadata'].get('deletionTimestamp') or not node['metadata'].get('uid'):
            raise RuntimeError('K3s node identity unavailable')
        if version == source:
            remaining.append(name)
        elif version != target or remaining:
            raise RuntimeError('K3s node order or runtime version differs')
    return remaining[0] if remaining else None
