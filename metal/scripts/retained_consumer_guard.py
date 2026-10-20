"""Prove exact completed read-only backup consumers; never change a scheduler."""

from contextlib import contextmanager
import hashlib
import json
import os
import tempfile

import etcd_recovery as common

CACHE = None


@contextmanager
def operator_access(config):
    """Reuse the existing inline operator configuration only in anonymous RAM."""
    global CACHE
    if (not isinstance(config, dict) or set(config) != {
            'apiVersion', 'kind', 'current-context', 'clusters', 'users', 'contexts'} or
            config['apiVersion'] != 'v1' or config['kind'] != 'Config' or
            config['current-context'] != 'default' or
            config['contexts'] != [{'name': 'default', 'context': {'cluster': 'default', 'user': 'default'}}] or
            len(config['clusters']) != 1 or len(config['users']) != 1):
        raise RuntimeError('existing inline operator configuration shape differs')
    cluster, user = config['clusters'][0], config['users'][0]
    if (set(cluster) != {'name', 'cluster'} or cluster['name'] != 'default' or
            set(cluster['cluster']) != {'server', 'certificate-authority-data'} or
            cluster['cluster']['server'] != 'https://10.0.20.50:6443' or
            set(user) != {'name', 'user'} or user['name'] != 'default' or
            set(user['user']) != {'client-certificate-data', 'client-key-data'} or
            not all(isinstance(value, str) and value for value in
                    [cluster['cluster']['certificate-authority-data'], *user['user'].values()])):
        raise RuntimeError('existing operator API, inline credentials or TLS contract differs')
    if not hasattr(os, 'memfd_create'):
        raise RuntimeError('anonymous Linux credential storage unavailable')
    descriptor = os.memfd_create('homelab-103-existing-operator', os.MFD_CLOEXEC)
    path = '/proc/' + str(os.getpid()) + '/fd/' + str(descriptor)
    previous = os.environ.get('KUBECONFIG')
    previous_cache = CACHE
    try:
        os.fchmod(descriptor, 0o600)
        data = common.canonical(config)
        if os.write(descriptor, data) != len(data):
            raise RuntimeError('incomplete anonymous operator configuration')
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.environ['KUBECONFIG'] = path
        with tempfile.TemporaryDirectory(prefix='homelab-103-consumer-', dir='/run') as cache:
            CACHE = cache
            yield path
    finally:
        CACHE = previous_cache
        if previous is None:
            os.environ.pop('KUBECONFIG', None)
        else:
            os.environ['KUBECONFIG'] = previous
        os.close(descriptor)


def uses(spec, claim):
    return any(v.get('persistentVolumeClaim', {}).get('claimName') == claim
               for v in spec.get('volumes', []))


def readonly(spec, claim):
    volumes = {v['name'] for v in spec.get('volumes', [])
               if v.get('persistentVolumeClaim', {}).get('claimName') == claim}
    if (len(volumes) != 1 or not spec.get('containers') or
            spec.get('restartPolicy') not in ('Never', 'OnFailure') or
            spec.get('initContainers') or spec.get('ephemeralContainers') or
            any(spec.get(k) for k in ('hostNetwork', 'hostPID', 'hostIPC')) or
            any('hostPath' in v for v in spec.get('volumes', []))):
        raise RuntimeError('backup consumer isolation differs')
    for container in spec['containers']:
        mounts = [m for m in container.get('volumeMounts', []) if m['name'] in volumes]
        security = container.get('securityContext', {})
        if (len(mounts) != 1 or mounts[0].get('readOnly') is not True or
                mounts[0].get('subPath') or mounts[0].get('subPathExpr') or
                security.get('privileged') or security.get('allowPrivilegeEscalation') is not False or
                security.get('capabilities', {}).get('drop') != ['ALL'] or
                security.get('capabilities', {}).get('add')):
            raise RuntimeError('backup consumer may write or escape its mount')


def pinned(resource, records):
    meta = resource['metadata']
    record = records.get(meta.get('name'), {})
    if (not meta.get('uid') or meta.get('deletionTimestamp') or meta['uid'] != record.get('uid') or
            hashlib.sha256(common.canonical(resource['spec'])).hexdigest() != record.get('spec_sha256')):
        raise RuntimeError('backup consumer UID or specification changed')


def owner(resource, kind, records):
    owners = [o for o in resource['metadata'].get('ownerReferences', []) if o.get('controller') is True]
    if (len(owners) != 1 or owners[0].get('apiVersion') != 'batch/v1' or owners[0].get('kind') != kind or
            not owners[0].get('uid') or
            records.get(owners[0].get('name'), {}).get('uid') != owners[0]['uid']):
        raise RuntimeError('backup consumer controlling owner changed')


def check(resources, namespace, profile):
    expected = profile['readonly_job_consumers']
    selected = {'cronjobs': [], 'jobs': [], 'pods': []}
    main = []
    for resource in resources:
        kind = resource.get('kind')
        if kind not in ('Pod', 'Job', 'CronJob'):
            raise RuntimeError('unexpected consumer resource kind')
        spec = resource['spec']
        template = (spec['jobTemplate']['spec']['template']['spec'] if kind == 'CronJob' else
                    spec['template']['spec'] if kind == 'Job' else spec)
        if not uses(template, profile['claim']):
            continue
        if resource['metadata'].get('namespace') != namespace:
            raise RuntimeError('consumer namespace differs')
        if kind == 'Pod' and resource['metadata'].get('uid') == profile['pod_uid']:
            if resource['metadata'].get('deletionTimestamp') or resource['status'].get('phase') != 'Running':
                raise RuntimeError('original writer is not running')
            main.append(resource)
            continue
        key = {'CronJob': 'cronjobs', 'Job': 'jobs', 'Pod': 'pods'}[kind]
        pinned(resource, expected[key])
        readonly(template, profile['claim'])
        selected[key].append(resource)
        status = resource.get('status', {})
        if kind == 'CronJob':
            if status.get('active'):
                raise RuntimeError('backup scheduler has active work')
        elif kind == 'Job':
            owner(resource, 'CronJob', expected['cronjobs'])
            conditions = status.get('conditions', [])
            if (any(status.get(k, 0) for k in ('active', 'terminating', 'failed')) or
                    status.get('succeeded') != 1 or
                    not any(c.get('type') == 'Complete' and c.get('status') == 'True' for c in conditions) or
                    any(c.get('type') in ('Failed', 'FailureTarget') and c.get('status') == 'True' for c in conditions)):
                raise RuntimeError('backup Job completion is unproven')
        else:
            owner(resource, 'Job', expected['jobs'])
            containers = status.get('containerStatuses', [])
            if (status.get('phase') != 'Succeeded' or not containers or status.get('initContainerStatuses') or
                    {c.get('name') for c in containers} != {c['name'] for c in spec['containers']} or
                    len(containers) != len(spec['containers']) or
                    any(c.get('state', {}).get('terminated', {}).get('exitCode') != 0 for c in containers)):
                raise RuntimeError('backup Pod completion is unproven')
    if len(main) != 1:
        raise RuntimeError('original writer missing or duplicated')
    for key, values in selected.items():
        names = [v['metadata']['name'] for v in values]
        if len(names) != len(set(names)) or set(names) != set(expected[key]):
            raise RuntimeError('backup consumer set changed')
    return {key: sorted(v['metadata']['uid'] for v in values) for key, values in selected.items()}


def observe(namespace, profile):
    if CACHE is None:
        raise RuntimeError('anonymous existing-operator context required')
    value = json.loads(common.command(['/usr/local/bin/k3s', 'kubectl', '--cache-dir=' + CACHE,
                                       'get', 'pods,jobs,cronjobs',
                                       '-n', namespace, '-o', 'json']).stdout)
    if value.get('kind') != 'List' or not isinstance(value.get('items'), list):
        raise RuntimeError('native consumer inventory missing')
    return check(value['items'], namespace, profile)
