#!/usr/bin/env python3
"""Build the exact fresh no-CSI Rook candidate; never connect or execute it."""

import hashlib
import re

import rook_disk_qualification as disks


NAMESPACE = 'rook-qualification'
CEPH_IMAGE = 'quay.io/ceph/ceph@sha256:6bb1c8a42fbc0bf87938946990b65174466997bc11c31eb5a323225a779fd8f9'
OPERATORS = {
    '1.20.9': {
        'package': 'rook-ceph-v1.20.9.tgz',
        'package_sha256': '20c4eb7bb35d64e9e671b9d4e9e314b1a4287d9fc993b0fa28b63249237e309f',
        'image_sha256': 'ff15952bc8eb1a55519b46ef3923cc4afa70d1d8f5fe1cd4f0bae74e28f84605',
        'render_sha256': '529e0335f07b712366331a1156c5e6dd38d9be51eb8a80a3d708ead2c95e25af',
    },
    '1.21.0': {
        'package': 'rook-ceph-1.21.0.tgz',
        'package_sha256': 'c070c7985deee72d7620e0377c07ce2afba28f566fbefe47bf934d00a5692cde',
        'image_sha256': '2c3a65786d3cc85ba15d7f258461c0bf392c6a6ee19dde8011259b8d34eeedd0',
        'render_sha256': '9c557ce0a8bd2413b7799eb3eb63a8399c9edc5e9bb2de6c15461ab16ec96f9f',
    },
}
DEFAULTS = {'osd_pool_default_size': '2', 'osd_pool_default_min_size': '2',
            'mon_allow_pool_size_one': 'false'}


def operator_values(version):
    if version not in OPERATORS:
        raise RuntimeError('unreviewed Rook operator version')
    return {'csi': {'installCsiOperator': False, 'createCsiOperatorResources': False},
            'image': {'repository': 'docker.io/rook/ceph',
                      'tag': 'v' + version + '@sha256:' + OPERATORS[version]['image_sha256']},
            'currentNamespaceOnly': True, 'enableDiscoveryDaemon': False,
            'disableDeviceHotplug': True}


def require_operator_render(version, raw):
    if (version not in OPERATORS or not isinstance(raw, bytes) or
            hashlib.sha256(raw).hexdigest() != OPERATORS[version]['render_sha256']):
        raise RuntimeError('reviewed no-CSI operator render differs')


def resources(cluster_name, disk_run_id, inventory):
    if (not re.fullmatch(r'qualification-[a-f0-9]{8}', cluster_name) or
            not re.fullmatch(r'rook-[a-f0-9]{8}', disk_run_id)):
        raise RuntimeError('foreign private cluster or disk run identity')
    names = [disk_run_id + '-' + str(number) for number in range(3)]
    selected = disks.guest_disks(inventory, names)
    nodes = [{'name': 'k3d-' + cluster_name + suffix, 'devices': [{'name': device['path']}],
              'config': {'osdsPerDevice': '1'}}
             for suffix, device in zip(('-server-0', '-agent-0', '-agent-1'), selected)]
    return [
        {'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': NAMESPACE}},
        {'apiVersion': 'v1', 'kind': 'ConfigMap',
         'metadata': {'name': 'rook-config-override', 'namespace': NAMESPACE},
         'data': {'config': '[global]\n' + ''.join(key + ' = ' + value + '\n'
                                                 for key, value in DEFAULTS.items())}},
        {'apiVersion': 'ceph.rook.io/v1', 'kind': 'CephCluster',
         'metadata': {'name': NAMESPACE, 'namespace': NAMESPACE},
         'spec': {
             'cephVersion': {'image': CEPH_IMAGE, 'allowUnsupported': False},
             'dataDirHostPath': '/var/lib/rook-qualification',
             'mon': {'count': 3, 'allowMultiplePerNode': False},
             'mgr': {'count': 2, 'allowMultiplePerNode': False,
                     'modules': [{'name': 'rook', 'enabled': True}]},
             'csi': {'skipUserCreation': True},
             # Explicit daemon.keyType also enables Rook's emergency cipher override.
             'security': {'cephx': {'daemon': {'keyRotationPolicy': 'KeyGeneration',
                                             'keyGeneration': 1},
                                    'allowedCiphers': ['aes256k']}},
             'network': {'connections': {'encryption': {'enabled': True},
                                         'requireMsgr2': True}},
             'storage': {'useAllNodes': False, 'useAllDevices': False, 'nodes': nodes},
             'cephConfig': {'global': dict(DEFAULTS)},
             'skipUpgradeChecks': False,
             'continueUpgradeAfterChecksEvenIfNotHealthy': False,
             'removeOSDsIfOutAndSafeToRemove': False,
             'disruptionManagement': {'managePodBudgets': True},
             'resources': {
                 'mon': {'requests': {'cpu': '100m', 'memory': '256Mi'},
                         'limits': {'memory': '512Mi'}},
                 'mgr': {'requests': {'cpu': '100m', 'memory': '512Mi'},
                         'limits': {'memory': '1Gi'}},
                 'osd': {'requests': {'cpu': '100m', 'memory': '512Mi'},
                         'limits': {'memory': '2Gi'}},
             },
         }},
        {'apiVersion': 'ceph.rook.io/v1', 'kind': 'CephBlockPool',
         'metadata': {'name': 'qualification', 'namespace': NAMESPACE},
         'spec': {'failureDomain': 'host', 'replicated': {'size': 2, 'requireSafeReplicaSize': True},
                  'parameters': {'min_size': '2'}}},
    ]
