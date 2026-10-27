#!/usr/bin/env python3
"""Issue 103: retire four resolved failed Job records after exact successful recovery."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
DIGEST = 'sha256:ee4876e6add9b45af87dd94af9fb9cd0cfca5d7f673e215c456f341983bb7113'
TARGETS = {
    ('pointview', 'pointview-retention-29884890'): ('2088d176-bdb9-42df-bc35-3d413283805c', 'eede725c-f9c0-438c-8593-5c9e155acc61'),
    ('pointview', 'pointview-triage-29884800'): ('c2bf46f4-0324-451b-9318-079e835953d5', '50610e53-b900-46b3-8955-c11bd602b567'),
    ('pointview-canary', 'pointview-canary-retention-29884890'): ('c367bae2-acee-47a2-a744-658f916f366e', 'd98b2b80-4695-468c-946b-7b52edacbd6e'),
    ('pointview-canary', 'pointview-canary-triage-29884800'): ('33cc4aec-4521-49cf-ab90-a205e425e3a0', '6527a8a7-896d-4b83-b12f-44b75fac4ab2'),
}
CLEANUP = {
    ('pointview-canary', 'triage'): ('38642328-d9c8-49b0-8fbc-7bd9a355676e', '7b079d41-8adb-407b-ae70-1017ab92893d'),
    ('pointview-canary', 'retention'): ('a888ec90-3b32-4c7d-a3ae-37dfcdd140a4', 'b437e4bf-f58b-4583-a25c-9205c7c47cd2'),
    ('pointview', 'triage'): ('356c25a4-b88b-4cd9-b7cb-4ccc6588d078', '60342f08-017c-46e5-b317-646d1970b751'),
    ('pointview', 'retention'): ('2f811967-cb0d-4468-bac5-5c75f2036ec8', '8f3194b9-52e9-4300-bae2-5af480387762'),
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def run(argv, data=None):
    result = subprocess.run(argv, input=data, text=True, capture_output=True, cwd=ROOT, timeout=60)
    require(result.returncode == 0, 'Command failed or outcome uncertain; observe without replay')
    return result.stdout


def old_job(job, namespace, name):
    uid, cron_uid = TARGETS[(namespace, name)]
    meta, status = job['metadata'], job['status']
    require(meta['uid'] == uid and meta['name'] == name and meta['namespace'] == namespace
            and meta.get('resourceVersion') and not meta.get('deletionTimestamp'), 'Failed Job identity changed')
    owners = meta.get('ownerReferences', [])
    require(len(owners) == 1 and owners[0]['kind'] == 'CronJob' and owners[0]['uid'] == cron_uid
            and owners[0]['controller'] is True, 'Failed Job ownership changed')
    require(not status.get('active') and not status.get('succeeded') and any(
        c['type'] == 'Failed' and c['status'] == 'True' and c['reason'] == 'DeadlineExceeded'
        for c in status.get('conditions', [])), 'Job is not the resolved deadline failure')
    require(meta['creationTimestamp'] == ('2026-10-27T08:00:00Z' if '-triage-' in name else '2026-10-27T09:30:00Z'), 'Failure is not the recorded baseline')
    return owners[0]['name'], cron_uid


def cleanup_proof(job, pods, cron, namespace, task, event):
    job_uid, pod_uid = CLEANUP[(namespace, task)]
    require(job['metadata']['uid'] == job_uid and not job['metadata'].get('deletionTimestamp')
            and not job['status'].get('active') and not job['status'].get('failed')
            and job['status'].get('succeeded') == 1 and job['status'].get('completionTime')
            and any(c['type'] == 'Complete' and c['status'] == 'True' for c in job['status']['conditions']),
            'Completed recovery Job identity/status changed')
    owner = job['metadata']['ownerReferences']
    require(len(owner) == 1 and owner[0]['controller'] is True and owner[0]['kind'] == 'CronJob'
            and owner[0]['name'] == namespace + '-' + task and owner[0]['uid'] == cron['metadata']['uid'],
            'Native CronJob owner changed')
    require(not cron['status'].get('active') and cron['status']['lastSuccessfulTime'] >= job['status']['completionTime']
            and cron['status']['lastSuccessfulTime'] > cron['status']['lastScheduleTime'], 'CronJob recovery not proven')
    require(len(pods) == 1, 'Completed recovery Pod is ambiguous')
    pod = pods[0]
    require(pod['metadata']['uid'] == pod_uid and not pod['metadata'].get('deletionTimestamp')
            and pod['status']['phase'] == 'Succeeded' and pod['spec']['nodeName'] == 'pikachu'
            and pod['spec']['restartPolicy'] == 'Never'
            and not pod['spec'].get('initContainers'), 'Completed recovery Pod identity/status changed')
    owner = pod['metadata']['ownerReferences']
    require(len(owner) == 1 and owner[0]['uid'] == job_uid and owner[0]['controller'] is True,
            'Completed recovery Pod owner changed')
    containers = pod['status']['containerStatuses']
    require(len(containers) == 1 and containers[0]['restartCount'] == 0
            and containers[0]['state']['terminated']['exitCode'] == 0
            and containers[0]['imageID'].endswith('@' + DIGEST), 'Original successful image execution missing')
    require(event['event'] == 'maintenance.empty-jobs.completed'
            and event['retention' if task == 'triage' else 'triage'] is None, 'Recovery task result changed')
    result = event[task]
    require(result['event'] == task + '.completed', 'Original task completion missing')
    if task == 'triage':
        require(result['completed'] == result['needsAttention'] == 0 and result['stopReason'] == 'QUEUE_EMPTY',
                'Triage did not prove empty successful execution')
    else:
        require(all(result[k] == 0 for k in ('selected', 'deleted', 'failed', 'deletedBytes')),
                'Retention did not prove empty successful execution')


def cleanup_recovery(base, get, head, apply):
    results = []
    for namespace, task in CLEANUP:
        require('maintenanceEmptyJobs:\n  enabled: false' in run(
            ['git', 'show', head + ':apps/' + namespace + '/values.yaml']), 'Recovery still desired in published source')
        app = get('applications.argoproj.io', 'argocd', namespace)
        require(app['status']['sync']['status'] == 'Synced' and app['status']['sync']['revision'] == head
                and app['status']['health']['status'] == 'Healthy', 'Application not reconciled and healthy')
        name = 'maintenance-103-' + task + '-20261027-a'
        job = get('job', namespace, name)
        if job is None:
            results.append({'namespace': namespace, 'name': name, 'already_absent': True})
            continue
        pods = get('pods', namespace, selector='job-name=' + name)['items']
        cron = get('cronjob', namespace, namespace + '-' + task)
        lines = run(base + ['logs', '-n', namespace, 'job/' + name, '-c', 'recovery']).splitlines()
        require(len(lines) == 1, 'Completed recovery result is ambiguous')
        cleanup_proof(job, pods, cron, namespace, task, json.loads(lines[0]))
        require(get('job', namespace, name) == job, 'Completed recovery Job changed before deletion')
        if apply:
            options = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'propagationPolicy': 'Foreground',
                       'preconditions': {'uid': job['metadata']['uid'], 'resourceVersion': job['metadata']['resourceVersion']}}
            run(base + ['delete', '--raw', '/apis/batch/v1/namespaces/' + namespace + '/jobs/' + name, '-f', '-'], json.dumps(options))
            # Observe this single dispatch to completion; never replay a pending delete.
            while get('job', namespace, name) is not None:
                time.sleep(2)
            require(not get('pods', namespace, selector='job-name=' + name)['items'], 'Completed recovery Pod remains')
            current = get('cronjob', namespace, namespace + '-' + task)
            require(current['metadata']['uid'] == cron['metadata']['uid'] and current['spec'] == cron['spec']
                    and current['status']['lastSuccessfulTime'] == cron['status']['lastSuccessfulTime'],
                    'Original CronJob changed after completed history cleanup')
        results.append({'namespace': namespace, 'name': name, 'uid': job['metadata']['uid'], 'applied': apply})
    return {'source': head, 'results': results, 'scope': 'four completed recovery Jobs and their Pods only'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubectl', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--cleanup-recovery', action='store_true')
    args = parser.parse_args()
    require(ROOT == Path('/Users/chris/Documents/Github/homelab'), 'Canonical checkout required')
    require(run(['git', 'branch', '--show-current']).strip() == 'master'
            and run(['git', 'remote', 'get-url', 'origin']).strip() == 'git@git.eaglepass.io:ops/homelab.git',
            'Canonical Gitea master required')
    head = run(['git', 'rev-parse', 'HEAD']).strip()
    require(run(['git', 'ls-remote', 'origin', 'refs/heads/master']).split()[0] == head, 'Source not published')
    relative = str(Path(__file__).relative_to(ROOT))
    require(run(['git', 'show', head + ':' + relative]) == Path(__file__).read_text(), 'Executor source is dirty')
    cache = Path(os.environ['KUBECACHEDIR'])
    require(cache.is_absolute(), 'Private cache required')
    base = [args.kubectl, '--kubeconfig', str(ROOT / 'metal/kubeconfig.yaml'), '--cache-dir', str(cache), '--request-timeout=30s']
    config = json.loads(run(base + ['config', 'view', '--minify', '-o', 'json']))
    cluster = config['clusters'][0]['cluster']
    require(len(config['clusters']) == 1 and cluster['server'] == 'https://10.0.20.50:6443'
            and (cluster.get('certificate-authority-data') or cluster.get('certificate-authority'))
            and not any(cluster.get(k) for k in ('insecure-skip-tls-verify', 'proxy-url', 'tls-server-name')),
            'Kubernetes TLS identity changed')
    versions = json.loads(run(base + ['version', '-o', 'json']))
    require(versions['clientVersion']['major'] == versions['serverVersion']['major'] == '1'
            and abs(int(versions['clientVersion']['minor']) - int(versions['serverVersion']['minor'])) <= 1,
            'Unsupported Kubernetes client skew')

    def get(kind, namespace, name=None, selector=None):
        argv = base + ['get', kind, '-n', namespace]
        if name:
            argv += [name, '--ignore-not-found']
        if selector:
            argv += ['-l', selector]
        raw = run(argv + ['-o', 'json'])
        return json.loads(raw) if raw.strip() else None

    if args.cleanup_recovery:
        print(json.dumps(cleanup_recovery(base, get, head, args.apply)))
        return

    def verify_recovery(namespace):
        for task in ('triage', 'retention'):
            name = 'maintenance-103-' + task + '-20261027-a'
            job = get('job', namespace, name)
            pods = get('pods', namespace, selector='job-name=' + name)['items']
            cron = get('cronjob', namespace, namespace + '-' + task)
            lines = run(base + ['logs', '-n', namespace, 'job/' + name, '-c', 'recovery']).splitlines()
            require(len(lines) == 1, 'Recovery result is ambiguous')
            cleanup_proof(job, pods, cron, namespace, task, json.loads(lines[0]))
        app = get('applications.argoproj.io', 'argocd', namespace)
        require(app['status']['sync']['status'] == 'Synced' and app['status']['sync']['revision'] == head,
                'Desired-state repair is not reconciled')

    for namespace in sorted({namespace for namespace, _ in CLEANUP}):
        verify_recovery(namespace)
    results = []
    for namespace, name in TARGETS:
        job = get('job', namespace, name)
        if job is None:
            results.append({'namespace': namespace, 'name': name, 'already_absent': True})
            continue
        cron_name, cron_uid = old_job(job, namespace, name)
        cron = get('cronjob', namespace, cron_name)
        pod_spec = cron['spec']['jobTemplate']['spec']['template']['spec']
        require(cron['metadata']['uid'] == cron_uid and pod_spec['nodeSelector'] == {'kubernetes.io/hostname': 'pikachu'}
                and all(c['imagePullPolicy'] == 'IfNotPresent' and c['image'].endswith('@' + DIGEST)
                        for c in pod_spec['containers']), 'Future CronJob repair changed')
        require(not get('pods', namespace, selector='job-name=' + name)['items'], 'Original Job still has Pods')
        verify_recovery(namespace)
        current = get('job', namespace, name)
        require(current == job, 'Original Job changed before retirement')
        if args.apply:
            options = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'propagationPolicy': 'Foreground',
                       'preconditions': {'uid': job['metadata']['uid'], 'resourceVersion': job['metadata']['resourceVersion']}}
            run(base + ['delete', '--raw', '/apis/batch/v1/namespaces/' + namespace + '/jobs/' + name, '-f', '-'], json.dumps(options))
            require(get('job', namespace, name) is None, 'Deletion pending/uncertain; do not replay')
        results.append({'namespace': namespace, 'name': name, 'uid': job['metadata']['uid'], 'applied': args.apply})
    print(json.dumps({'source': head, 'results': results, 'scope': 'four resolved failed Job records only'}))


if __name__ == '__main__':
    main()
