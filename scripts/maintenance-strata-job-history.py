#!/usr/bin/env python3
"""Retire only Issue 103's three missed Strata backup Job records after recovery."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CRON_UID = '71e995a6-ea65-4272-8a00-27eac21edfc5'
CRON_SPEC = '938a0cd1a191542d475dceb068399330fa75b304c20791d00cdeaa727bbb8110'
DIGEST = 'sha256:71f04326edf6e1defeabf2dc211abcf6bc6c7e14b0838c9e0704ab12253b08f0'
TARGETS = {
    'strata-backup-29884200': '00e47580-2b04-49df-82d3-4edef6551ec5',
    'strata-backup-29884230': '85554a52-b73c-4ff6-843e-0b528ab873fe',
    'strata-backup-29884260': '2d869958-1c8b-4de8-aff9-37f89c302e66',
}


def require(value, message):
    if not value:
        raise RuntimeError(message)


def run(argv, data=None):
    result = subprocess.run(argv, input=data, text=True, capture_output=True, cwd=ROOT, timeout=60)
    require(result.returncode == 0, 'Command failed or outcome uncertain; observe without replay')
    return result.stdout


def owned(job):
    owners = job['metadata'].get('ownerReferences', [])
    require(len(owners) == 1 and owners[0].get('kind') == 'CronJob'
            and owners[0].get('name') == 'strata-backup' and owners[0].get('uid') == CRON_UID
            and owners[0].get('controller') is True, 'Original CronJob ownership changed')


def failed(job, name):
    meta, status = job['metadata'], job['status']
    require(meta['name'] == name and meta['namespace'] == 'strata' and meta['uid'] == TARGETS[name]
            and meta.get('resourceVersion') and not meta.get('deletionTimestamp'), 'Failed Job identity changed')
    owned(job)
    require(not status.get('active') and not status.get('succeeded') and not status.get('terminating')
            and any(c['type'] == 'Failed' and c['status'] == 'True' and c.get('reason') == 'DeadlineExceeded'
                    for c in status.get('conditions', [])), 'Recorded deadline failure is not inactive')


def recovered(job, pod, cron, job_uid, pod_uid):
    owned(job)
    require(job['metadata']['uid'] == job_uid and not job['metadata'].get('deletionTimestamp')
            and not job['status'].get('active') and not job['status'].get('failed')
            and job['status'].get('succeeded') == 1 and job['status'].get('completionTime', '') > '2026-10-26T23:15:00Z'
            and any(c['type'] == 'Complete' and c['status'] == 'True' for c in job['status'].get('conditions', [])),
            'New ordinary backup has not completed successfully')
    require(cron['metadata']['uid'] == CRON_UID and not cron['metadata'].get('deletionTimestamp')
            and hashlib.sha256(json.dumps(cron['spec'], sort_keys=True).encode()).hexdigest() == CRON_SPEC
            and cron['status'].get('lastSuccessfulTime', '') >= job['status']['completionTime'],
            'Original backup schedule or successful execution changed')
    owners = pod['metadata'].get('ownerReferences', [])
    require(pod['metadata']['uid'] == pod_uid and not pod['metadata'].get('deletionTimestamp')
            and len(owners) == 1 and owners[0].get('kind') == 'Job' and owners[0].get('uid') == job_uid
            and owners[0].get('controller') is True and pod['status']['phase'] == 'Succeeded'
            and pod['spec']['restartPolicy'] == 'OnFailure' and not pod['spec'].get('initContainers'),
            'Completed ordinary backup Pod evidence changed')
    statuses = pod['status'].get('containerStatuses', [])
    require(len(statuses) == 1 and statuses[0]['name'] == 'sqlite-backup'
            and statuses[0]['imageID'].endswith('@' + DIGEST) and statuses[0]['restartCount'] == 0
            and statuses[0]['state'].get('terminated', {}).get('exitCode') == 0,
            'Original backup image did not execute successfully')


def observe_deleted(get, name, uid):
    """Observe the one accepted foreground delete without another API write."""
    while True:
        current = get('job', name)
        if current is None:
            return
        require(current['metadata']['uid'] == uid and current['metadata'].get('deletionTimestamp'),
                'Deletion outcome changed or uncertain; observe without replay')
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubectl', required=True)
    parser.add_argument('--recovery-job', required=True)
    parser.add_argument('--recovery-job-uid', required=True)
    parser.add_argument('--recovery-pod-uid', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    require(re.fullmatch(r'strata-backup-[0-9]+', args.recovery_job)
            and args.recovery_job not in TARGETS, 'Unreviewed recovery Job name')
    require(ROOT == Path('/Users/chris/Documents/Github/homelab')
            and run(['git', 'branch', '--show-current']).strip() == 'master'
            and run(['git', 'remote', 'get-url', 'origin']).strip() == 'git@git.eaglepass.io:ops/homelab.git',
            'Canonical Gitea checkout required')
    head = run(['git', 'rev-parse', 'HEAD']).strip()
    require(run(['git', 'ls-remote', 'origin', 'refs/heads/master']).split()[0] == head
            and run(['git', 'show', head + ':' + str(Path(__file__).relative_to(ROOT))]) == Path(__file__).read_text(),
            'Executor source must be published and unchanged')
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

    def get(kind, name=None, selector=None):
        argv = base + ['get', kind, '-n', 'strata']
        if name:
            argv += [name, '--ignore-not-found']
        if selector:
            argv += ['-l', selector]
        raw = run(argv + ['-o', 'json'])
        return json.loads(raw) if raw.strip() else None

    def proof():
        job = get('job', args.recovery_job)
        pods = get('pods', selector='job-name=' + args.recovery_job)['items']
        require(job is not None and len(pods) == 1, 'Recovery evidence absent or ambiguous')
        recovered(job, pods[0], get('cronjob', 'strata-backup'), args.recovery_job_uid, args.recovery_pod_uid)
        lines = run(base + ['logs', pods[0]['metadata']['name'], '-n', 'strata', '-c', 'sqlite-backup']).splitlines()
        require(len(lines) == 1, 'Ordinary backup result is ambiguous')
        result = json.loads(lines[0])
        require(isinstance(result.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', result['sha256'])
                and re.fullmatch(r'/backup/automated-backups/strata-[0-9]{8}T[0-9]{6}Z\.sqlite\.gz', result.get('backup', ''))
                and isinstance(result.get('counts'), dict) and result['counts']
                and all(type(v) is int and v >= 0 for v in result['counts'].values()), 'Backup command result invalid')

    results = []
    for name in TARGETS:
        proof()
        job = get('job', name)
        if job is None:
            results.append({'name': name, 'already_absent': True})
            continue
        failed(job, name)
        require(not get('pods', selector='job-name=' + name)['items'], 'Failed Job still has Pods')
        require(get('job', name) == job, 'Failed Job changed before deletion')
        if args.apply:
            options = {'apiVersion': 'v1', 'kind': 'DeleteOptions', 'propagationPolicy': 'Foreground',
                       'preconditions': {'uid': job['metadata']['uid'], 'resourceVersion': job['metadata']['resourceVersion']}}
            run(base + ['delete', '--raw', '/apis/batch/v1/namespaces/strata/jobs/' + name, '-f', '-'], json.dumps(options))
            observe_deleted(get, name, job['metadata']['uid'])
        results.append({'name': name, 'uid': job['metadata']['uid'], 'applied': args.apply})
    proof()
    print(json.dumps({'source': head, 'results': results, 'scope': 'three resolved Kubernetes Job records only; no NAS access'}))


if __name__ == '__main__':
    main()
