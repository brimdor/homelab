#!/usr/bin/env python3
"""Issue 103: retire four resolved failed Job records after exact successful recovery."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
RECOVERY = 'maintenance-empty-jobs-103-20261026-a'
DIGEST = 'sha256:ee4876e6add9b45af87dd94af9fb9cd0cfca5d7f673e215c456f341983bb7113'
TARGETS = {
    ('pointview', 'pointview-retention-29883450'): ('5e2e2097-b4bb-421f-ac3d-c0237991c7a1', 'eede725c-f9c0-438c-8593-5c9e155acc61'),
    ('pointview', 'pointview-triage-29883360'): ('cfb8a9b7-284e-4fa3-9e63-93883c37ab46', '50610e53-b900-46b3-8955-c11bd602b567'),
    ('pointview-canary', 'pointview-canary-retention-29883450'): ('c72903d7-1682-4f22-8a84-697c4661e9c4', 'd98b2b80-4695-468c-946b-7b52edacbd6e'),
    ('pointview-canary', 'pointview-canary-triage-29883360'): ('b72b5495-5494-4ac0-b9c2-0dbf3a4d07c0', '6527a8a7-896d-4b83-b12f-44b75fac4ab2'),
}
REPLACEMENTS = {
    'pointview': ('a0ed3137-4411-47d2-9f93-530a5d71ab76', 'e114bd64-7dd3-4dd9-aeb3-8111859d4e9b'),
    'pointview-canary': ('d453c83e-556c-476c-84db-301919125895', '4ab1258b-fccf-4507-8cc8-aa8f44fcd798'),
}
CLEANUP = {
    ('pointview-canary', 'triage'): ('f5c8752d-d7aa-4836-95f0-cb376099e24c', 'ef1f8437-62a1-48d4-bef9-0dd8d0f0c9f7'),
    ('pointview-canary', 'retention'): ('da0d9e27-4d9b-44a3-8a7c-bccdda1b4b68', 'e670cb20-dbff-4556-b49a-d917efdf6600'),
    ('pointview', 'triage'): ('21befabe-500f-4e2e-a75c-911bed350071', 'f16e72d0-a839-4b4e-8f12-a604736c455f'),
    ('pointview', 'retention'): ('eb56e576-7117-4180-afce-9202cb4e0dc8', '787e207c-0305-4ccb-b1b8-e5e2639e5d73'),
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
    require(meta['creationTimestamp'] < '2026-10-26T11:23:00Z', 'Failure is not the recorded baseline')
    return owners[0]['name'], cron_uid


def replacement(job, pods, namespace, event):
    job_uid, pod_uid = REPLACEMENTS[namespace]
    require(job['metadata']['uid'] == job_uid and not job['metadata'].get('deletionTimestamp')
            and not job['status'].get('active') and not job['status'].get('failed')
            and job['status'].get('succeeded') == 1 and any(c['type'] == 'Complete' and c['status'] == 'True'
                for c in job['status'].get('conditions', [])), 'Successful recovery Job changed')
    require(len(pods) == 1, 'Recovery Pod evidence is ambiguous')
    pod = pods[0]
    require(pod['metadata']['uid'] == pod_uid and not pod['metadata'].get('deletionTimestamp')
            and pod['status']['phase'] == 'Succeeded' and pod['spec']['restartPolicy'] == 'Never'
            and pod['spec']['nodeName'] == 'growlithe', 'Recovery Pod identity/completion changed')
    owners = pod['metadata'].get('ownerReferences', [])
    require(len(owners) == 1 and owners[0]['uid'] == job_uid and owners[0]['controller'] is True,
            'Recovery Pod owner changed')
    containers = pod['status']['containerStatuses']
    require(len(containers) == 1 and containers[0]['imageID'].endswith('@' + DIGEST)
            and containers[0]['restartCount'] == 0 and containers[0]['state']['terminated']['exitCode'] == 0,
            'Original image execution not proven')
    require(event['event'] == 'maintenance.empty-jobs.completed'
            and event['triage']['event'] == 'triage.completed' and event['triage']['completed'] == 0
            and event['triage']['needsAttention'] == 0 and event['triage']['stopReason'] == 'QUEUE_EMPTY'
            and event['retention']['event'] == 'retention.completed'
            and all(event['retention'][k] == 0 for k in ('selected', 'deleted', 'failed', 'deletedBytes')),
            'Original commands did not prove safe successful execution')


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
            and pod['status']['phase'] == 'Succeeded' and pod['spec']['restartPolicy'] == 'Never'
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
        name = 'maintenance-103-' + task + '-20261026-b'
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
        job = get('job', namespace, RECOVERY)
        pods = get('pods', namespace, selector='job-name=' + RECOVERY)['items']
        lines = run(base + ['logs', '-n', namespace, 'job/' + RECOVERY, '-c', 'recovery']).splitlines()
        require(len(lines) == 1, 'Recovery result is ambiguous')
        replacement(job, pods, namespace, json.loads(lines[0]))
        app = get('applications.argoproj.io', 'argocd', namespace)
        require(app['status']['sync']['status'] == 'Synced' and app['status']['sync']['revision'] == head,
                'Desired-state repair is not reconciled')

    for namespace in REPLACEMENTS:
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
        require(cron['metadata']['uid'] == cron_uid and pod_spec['nodeSelector'] == {'kubernetes.io/hostname': 'growlithe'}
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
