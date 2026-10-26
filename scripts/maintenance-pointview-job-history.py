#!/usr/bin/env python3
"""Issue 103: retire four resolved failed Job records after exact successful recovery."""

import argparse
import json
import os
from pathlib import Path
import subprocess

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubectl', required=True)
    parser.add_argument('--apply', action='store_true')
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
