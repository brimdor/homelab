#!/usr/bin/env python3
"""Reviewed inputs and static identities for the isolated native CSI fixture."""

import copy
import hashlib
import json
import re
import uuid


NAMESPACE = 'ceph-csi-native'
CLIENT = 'ceph-csi-consumer'
BUNDLE = 'c354e4f8ac86cb3c0314171f898355a76770affe015bf4022ba93565fb812226'
IMAGES = ('quay.io/cephcsi/cephcsi:v3.17.1',
          'registry.k8s.io/sig-storage/csi-node-driver-registrar:v2.16.0',
          'registry.k8s.io/sig-storage/csi-attacher:v4.11.0',
          'docker.io/library/python:3.13-alpine')


def reviewed_objects(bundle, records):
    if hashlib.sha256(json.dumps(bundle, sort_keys=True, separators=(',', ':')).encode()).hexdigest() != BUNDLE:
        raise RuntimeError('native Ceph CSI upstream bundle changed')
    if (tuple(row['image'] for row in records) != IMAGES or
            any(set(row) != {'image', 'index_digest', 'digest'} or
                not all(re.fullmatch('sha256:[a-f0-9]{64}', row[key]) for key in ('index_digest', 'digest'))
                for row in records)):
        raise RuntimeError('native Ceph CSI immutable image inventory changed')
    pins = {row['image']: row['image'].rsplit(':', 1)[0] + '@' + row['digest'] for row in records}
    result = []
    for source in bundle['sources'].values():
        for original in source['objects']:
            obj = copy.deepcopy(original)
            kind = obj['kind']
            if kind not in ('ServiceAccount', 'ClusterRole', 'ClusterRoleBinding', 'Role', 'RoleBinding',
                            'Service', 'DaemonSet', 'Deployment', 'CSIDriver'):
                raise RuntimeError('foreign native CSI resource kind')
            if kind not in ('ClusterRole', 'ClusterRoleBinding', 'CSIDriver'):
                if obj['metadata'].get('namespace') not in (None, 'default'):
                    raise RuntimeError('foreign native CSI namespace')
                obj['metadata']['namespace'] = NAMESPACE
            for subject in obj.get('subjects', []):
                if subject['kind'] != 'ServiceAccount' or subject.get('namespace') not in (None, 'default'):
                    raise RuntimeError('foreign native CSI RBAC subject')
                subject['namespace'] = NAMESPACE
            if kind in ('DaemonSet', 'Deployment'):
                pod = obj['spec']['template']['spec']
                if kind == 'Deployment':
                    obj['spec']['replicas'] = 1
                    pod.pop('affinity', None)
                    retained = [container for container in pod['containers']
                                if container['name'] in ('csi-rbdplugin', 'csi-cephfsplugin', 'csi-attacher')]
                    if len(retained) != 2:
                        raise RuntimeError('static CSI controller actors differ')
                    pod['containers'] = retained
                for container in pod['containers'] + pod.get('initContainers', []):
                    if container['image'] not in pins:
                        raise RuntimeError('unreviewed static CSI image')
                    container['image'] = pins[container['image']]
                    container['imagePullPolicy'] = 'Never'
            result.append(obj)
    if (len([obj for obj in result if obj['kind'] == 'DaemonSet']) != 2 or
            len([obj for obj in result if obj['kind'] == 'Deployment']) != 2 or
            len([obj for obj in result if obj['kind'] == 'CSIDriver']) != 2):
        raise RuntimeError('native CSI workload inventory changed')
    return result


def static_binding(kind, cluster):
    if kind not in ('rbd', 'cephfs') or not isinstance(cluster, str):
        raise RuntimeError('foreign static CSI backend identity')
    try:
        valid = str(uuid.UUID(cluster)) == cluster
    except ValueError:
        valid = False
    if not valid:
        raise RuntimeError('foreign static CSI backend identity')
    attributes = {'clusterID': cluster, 'staticVolume': 'true'}
    if kind == 'rbd':
        attributes.update(pool='qualification-rbd', imageFeatures='layering', mapOptions='krbd:ms_mode=secure')
    else:
        attributes.update(fsName='qualificationfs', rootPath='/', mounter='kernel')
    name = 'qualification-csi-' + kind
    mode = 'ReadWriteOnce' if kind == 'rbd' else 'ReadWriteMany'
    csi = {'driver': kind + '.csi.ceph.com', 'volumeHandle': name,
           'nodeStageSecretRef': {'name': kind + '-credential', 'namespace': NAMESPACE},
           'volumeAttributes': attributes}
    if kind == 'rbd':
        csi['fsType'] = 'ext4'
    pv = {'apiVersion': 'v1', 'kind': 'PersistentVolume', 'metadata': {'name': name}, 'spec': {
        'capacity': {'storage': '128Mi'}, 'accessModes': [mode], 'volumeMode': 'Filesystem',
        'storageClassName': '', 'persistentVolumeReclaimPolicy': 'Retain', 'csi': csi,
        'claimRef': {'name': kind, 'namespace': CLIENT}}}
    pvc = {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
           'metadata': {'name': kind, 'namespace': CLIENT}, 'spec': {
               'accessModes': [mode], 'volumeMode': 'Filesystem', 'storageClassName': '',
               'volumeName': name, 'resources': {'requests': {'storage': '128Mi'}}}}
    if kind == 'cephfs':
        pv['spec']['mountOptions'] = ['ms_mode=secure']
    return pv, pvc
