#!/usr/bin/env python3
"""Persistent Kured-compatible ownership; no host, package or scheduling actions."""

import argparse
import copy
from datetime import datetime, timezone
import json
import re
import subprocess
import uuid


LOCK = 'weave.works/kured-node-lock'
JOURNAL = 'homelab.eaglepass.io/maintenance-owner'
IMAGE = 'ghcr.io/kubereboot/kured:1.21.0@sha256:76567a71427b074bfc51df6797c8c30ba44c9678ace7cd61a186ddb662ce97b1'
ARGS = [
    '--ds-name=kured', '--ds-namespace=kured', '--metrics-port=8080',
    '--lock-release-delay=10m', '--end-time=7:00', '--period=5m',
    '--drain-timeout=20m', '--reboot-days=mo', '--reboot-days=we',
    '--reboot-days=fr', '--reboot-sentinel=/sentinel/reboot-required',
    '--reboot-command=/bin/systemctl reboot', '--start-time=1:45',
    '--time-zone=America/Chicago', '--annotate-nodes=true',
    '--prefer-no-schedule-taint=homelab.eaglepass.io/rebooting',
    '--log-format=text', '--concurrency=1',
]
ENV = [{'name': 'KURED_NODE_ID', 'valueFrom': {
    'fieldRef': {'apiVersion': 'v1', 'fieldPath': 'spec.nodeName'}}}]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def reviewed_hop(node, source, target):
    return (type(source) is int and type(target) is int and
            ((source, target) in ((39, 41), (41, 43), (43, 44)) or
             node == 'totodile' and source == target == 44))


def rollout_ready(meta, status, expected):
    return (status.get('observedGeneration') == meta['generation'] and
            all(status.get(k) == expected for k in (
                'desiredNumberScheduled', 'currentNumberScheduled', 'updatedNumberScheduled',
                'numberReady', 'numberAvailable')) and status.get('numberMisscheduled', 0) == 0)



def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


class Kubectl:
    """Use the caller's existing secure context and process-local cache routing."""

    def __init__(self, executable):
        require(executable.startswith('/'), 'kubectl must be an absolute compatible executable')
        self.executable = executable

    def call(self, *args, data=None):
        result = subprocess.run([self.executable, *args], input=data, capture_output=True, check=False)
        # Only fixed nonsecret resources enter this adapter. Do not retain arbitrary stderr.
        require(result.returncode == 0, 'kubectl failed; observe ownership before retrying')
        return json.loads(result.stdout)

    def snapshot(self):
        return (self.call('get', 'daemonset', 'kured', '-n', 'kured', '-o', 'json'),
                self.call('get', 'pods', '-n', 'kured', '-o', 'json')['items'],
                self.call('get', 'nodes', '-o', 'json')['items'])

    def patch(self, operations):
        return self.call('patch', 'daemonset', 'kured', '-n', 'kured',
                         '--type=json', '--patch', encoded(operations), '-o', 'json')


class Ownership:
    """One durable owner shared with Kured, retained on errors and process exit.

    Locking is runtime coordination, not a DaemonSet configuration/deployment fix.
    Host actor holds and full health/recovery gates belong to the future controller.
    """

    def __init__(self, api, daemonset_uid, node_uids):
        require(isinstance(daemonset_uid, str) and daemonset_uid, 'missing expected DaemonSet UID')
        require(isinstance(node_uids, dict) and node_uids and
                all(isinstance(k, str) and k and isinstance(v, str) and v
                    for k, v in node_uids.items()), 'missing exact active node identities')
        require('chikorita' not in node_uids, 'retired node is not an active target')
        self.api, self.uid, self.nodes = api, daemonset_uid, dict(node_uids)

    def observed(self):
        ds, pods, nodes = self.api.snapshot()
        meta = ds['metadata']
        require(meta['uid'] == self.uid and meta['name'] == 'kured' and
                meta['namespace'] == 'kured' and not meta.get('deletionTimestamp'),
                'Kured controller identity changed')
        require({n['metadata']['name']: n['metadata']['uid'] for n in nodes} == self.nodes,
                'active node identities changed')
        protected_since = self.protected_since(ds)
        for node in nodes:
            require(not node['metadata'].get('deletionTimestamp'), 'node is deleting')
            conditions = {c['type']: c['status'] for c in node['status']['conditions']}
            require(conditions.get('Ready') == 'True' and all(
                conditions.get(k) == 'False' for k in ('MemoryPressure', 'DiskPressure', 'PIDPressure')),
                'node health does not permit ownership transition')
            pending = node['metadata'].get('annotations', {}).get(
                'weave.works/kured-reboot-in-progress', 'false')
            if pending != 'false':
                # Kured 1.21 annotates before Acquire: a request queued behind our
                # continuously held lock is not an active reboot. Older requests
                # and any unrecognized/expired lock still fail closed.
                try:
                    requested = datetime.fromisoformat(pending.replace('Z', '+00:00'))
                    require(protected_since is not None and requested.utcoffset() is not None and
                            protected_since <= requested <= datetime.now(timezone.utc),
                            'Kured reboot request predates verified maintenance lock')
                except (TypeError, ValueError, AttributeError) as error:
                    raise RuntimeError('invalid Kured reboot request time') from error
        expected = len(self.nodes)
        status = ds['status']
        require(rollout_ready(meta, status, expected), 'Kured rollout is incomplete ' + encoded({
            'expected': expected, 'generation': meta['generation'], 'status': status}))
        self.runtime(ds['spec']['template']['spec'])
        owned = [p for p in pods if any(o.get('uid') == self.uid and
                 o.get('controller') is True for o in p['metadata'].get('ownerReferences', []))]
        require(len(owned) == len(pods), 'foreign or orphan Pod in Kured namespace')
        require(len(owned) == expected and
                {p['spec']['nodeName'] for p in owned} == set(self.nodes),
                'Kured Pod coverage differs')
        for pod in owned:
            require(not pod['metadata'].get('deletionTimestamp') and
                    pod['status']['phase'] == 'Running', 'Kured Pod is not active')
            self.runtime(pod['spec'])
            containers = pod['status'].get('containerStatuses', [])
            require(len(containers) == 1 and containers[0]['name'] == 'kured' and
                    containers[0].get('ready') is True and
                    containers[0].get('imageID') == IMAGE.replace(':1.21.0', ''),
                    'Kured container is unready or image differs')
        return ds

    @staticmethod
    def runtime(spec):
        require(not spec.get('initContainers') and len(spec['containers']) == 1,
                'unexpected Kured process container')
        container = spec['containers'][0]
        require(container['name'] == 'kured' and container['image'] == IMAGE and
                container.get('command') == ['/usr/bin/kured'] and
                container.get('args') == ARGS and container.get('env') == ENV and
                not container.get('envFrom'), 'unreviewed Kured process configuration')

    def patch(self, ds, changes):
        metadata = ds['metadata']
        operations = [
            {'op': 'test', 'path': '/metadata/uid', 'value': self.uid},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': metadata['resourceVersion']},
        ]
        # Replacing only this map preserves all unrelated annotations under the RV test.
        annotations = copy.deepcopy(metadata.get('annotations', {}))
        for key, value in changes.items():
            if value is None:
                del annotations[key]
            else:
                annotations[key] = value
        operations.append({'op': 'add', 'path': '/metadata/annotations', 'value': annotations})
        self.api.patch(operations)

    def acquire(self, node, source, target, revision):
        require(node in self.nodes and reviewed_hop(node, source, target),
                'unreviewed node or Fedora hop')
        require(isinstance(revision, str) and re.fullmatch('[0-9a-f]{40}', revision),
                'missing exact published repository revision')
        ds = self.observed()
        annotations = ds['metadata'].get('annotations', {})
        skip_lock = None
        if LOCK in annotations and JOURNAL not in annotations:
            from maintenance_kured_20261026 import EXPIRES, OWNER
            candidate = json.loads(annotations[LOCK])
            created = datetime.fromisoformat(candidate['created'].replace('Z', '+00:00'))
            require(candidate.get('nodeID') == OWNER and type(candidate.get('TTL')) is int and
                    candidate['TTL'] > 0 and candidate.get('metadata') == {'unschedulable': True} and
                    abs((EXPIRES - created).total_seconds() - candidate['TTL'] / 1_000_000_000) < 0.001,
                    'foreign reboot lock; do not steal it')
            skip_lock = candidate
        require((LOCK not in annotations or skip_lock is not None) and JOURNAL not in annotations,
                'ownership already exists; inspect and resume, never steal')
        token = 'homelab-maintenance-103-' + str(uuid.uuid4())
        created = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        journal = {'version': 1, 'owner': token, 'node': node, 'node_uid': self.nodes[node],
                   'source': source, 'target': target, 'revision': revision, 'created': created,
                   'phase': 'OWNED_KURED_ONLY'}
        if skip_lock is not None:
            journal['restore_window_lock'] = skip_lock
        lock = {'nodeID': token, 'metadata': {'unschedulable': True}, 'created': created, 'TTL': 0}
        self.patch(ds, {LOCK: encoded(lock), JOURNAL: encoded(journal)})
        return self.resume(token)

    def resume(self, token):
        return self.ownership(self.observed(), token)

    def ownership(self, ds, token):
        require(isinstance(token, str) and re.fullmatch(
            r'homelab-maintenance-103-[0-9a-f-]{36}', token), 'invalid maintenance owner')
        annotations = ds['metadata'].get('annotations', {})
        try:
            lock, journal = json.loads(annotations[LOCK]), json.loads(annotations[JOURNAL])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError('missing or malformed persistent ownership') from error
        require(isinstance(lock, dict) and isinstance(journal, dict), 'invalid ownership shape')
        require(lock.get('nodeID') == token and lock.get('TTL') == 0 and
                type(lock.get('TTL')) is int and journal.get('owner') == token and
                journal.get('version') == 1 and journal.get('phase') == 'OWNED_KURED_ONLY' and
                journal.get('node') in self.nodes and
                journal.get('node_uid') == self.nodes[journal['node']] and
                reviewed_hop(journal.get('node'), journal.get('source'), journal.get('target')) and
                isinstance(journal.get('revision'), str) and
                re.fullmatch('[0-9a-f]{40}', journal['revision']) and
                lock.get('created') == journal.get('created') and
                lock.get('metadata') == {'unschedulable': True}, 'ownership contract differs')
        try:
            created = datetime.fromisoformat(journal['created'].replace('Z', '+00:00'))
            require(created.utcoffset() is not None, 'owner creation time lacks timezone')
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise RuntimeError('invalid owner creation time') from error
        return copy.deepcopy(journal)

    def protected_since(self, ds):
        annotations = ds['metadata'].get('annotations', {})
        if JOURNAL in annotations:
            journal = json.loads(annotations[JOURNAL])
            verified = self.ownership(ds, journal.get('owner'))
            created = datetime.fromisoformat(verified['created'].replace('Z', '+00:00'))
            saved = verified.get('restore_window_lock')
            if saved is not None:
                # Expiry does not break a nonexpiring owner acquired within the window.
                since = self.window_since(saved, created)
                if since is not None:
                    return min(created, since)
            return created
        if LOCK in annotations:
            return self.window_since(json.loads(annotations[LOCK]))
        return None

    @staticmethod
    def window_since(lock, at=None):
        from maintenance_kured_20261026 import EXPIRES, OWNER
        created = datetime.fromisoformat(lock['created'].replace('Z', '+00:00'))
        if (lock.get('nodeID') == OWNER and type(lock.get('TTL')) is int and
                lock['TTL'] > 0 and lock.get('metadata') == {'unschedulable': True} and
                abs((EXPIRES - created).total_seconds() - lock['TTL'] / 1_000_000_000) < 0.001 and
                created <= (at if at is not None else datetime.now(timezone.utc)) < EXPIRES):
            return created
        return None

    def clear_queued_requests(self, token, journal):
        """Clear proven requests blocked by this owner, before releasing its lock."""
        key = 'weave.works/kured-reboot-in-progress'
        pointer = '/metadata/annotations/' + key.replace('/', '~1')
        for node in self.api.call('get', 'nodes', '-o', 'json')['items']:
            ds = self.observed()
            require(self.ownership(ds, token) == journal, 'owner changed before queued-request cleanup')
            node = self.api.call('get', 'node', node['metadata']['name'], '-o', 'json')
            metadata = node['metadata']
            pending = metadata.get('annotations', {}).get(key, 'false')
            if pending == 'false':
                continue
            requested = datetime.fromisoformat(pending.replace('Z', '+00:00'))
            since = self.protected_since(ds)
            require(since is not None and requested.utcoffset() is not None and
                    since <= requested <= datetime.now(timezone.utc), 'unproven queued reboot request')
            operations = [
                {'op': 'test', 'path': '/metadata/uid', 'value': self.nodes[metadata['name']]},
                {'op': 'test', 'path': '/metadata/resourceVersion', 'value': metadata['resourceVersion']},
                {'op': 'test', 'path': pointer, 'value': pending},
                {'op': 'remove', 'path': pointer},
            ]
            self.api.call('patch', 'node', metadata['name'], '--type=json', '--patch',
                          encoded(operations), '-o', 'json')
            after = self.api.call('get', 'node', metadata['name'], '-o', 'json')
            require(after['metadata']['uid'] == metadata['uid'] and
                    key not in after['metadata'].get('annotations', {}),
                    'queued-request cleanup uncertain; observe before another action')

    def release(self, token, verify_safe_release):
        # No CLI exposes this: the future controller must supply real acceptance gates.
        journal = self.resume(token)
        require(verify_safe_release(copy.deepcopy(journal)) is True,
                'release health/actor/sentinel gates did not pass')
        ds = self.observed()
        require(json.loads(ds['metadata']['annotations'][JOURNAL]) == journal,
                'ownership changed during release verification')
        lock = json.loads(ds['metadata']['annotations'][LOCK])
        require(lock.get('nodeID') == token and type(lock.get('TTL')) is int and
                lock['TTL'] == 0 and lock.get('created') == journal['created'],
                'Kured ownership changed during release verification')
        restore = journal.get('restore_window_lock')
        if restore is not None:
            from maintenance_kured_20261026 import EXPIRES, OWNER
            require(restore.get('nodeID') == OWNER and type(restore.get('TTL')) is int and
                    restore['TTL'] > 0 and abs((EXPIRES - datetime.fromisoformat(
                        restore['created'].replace('Z', '+00:00'))).total_seconds() -
                        restore['TTL'] / 1_000_000_000) < 0.001,
                    'saved one-night lock changed; retain maintenance ownership')
            if datetime.now(timezone.utc) >= EXPIRES:
                restore = None
                self.clear_queued_requests(token, journal)
                ds = self.observed()
                require(self.ownership(ds, token) == journal, 'owner changed during queued-request cleanup')
        self.patch(ds, {LOCK: encoded(restore) if restore is not None else None, JOURNAL: None})
        after = self.observed()['metadata'].get('annotations', {})
        require(JOURNAL not in after and (after.get(LOCK) == encoded(restore)
                if restore is not None else LOCK not in after),
                'release response uncertain; inspect before another action')
        return journal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubectl', required=True)
    parser.add_argument('operation', choices=['inspect'])
    args = parser.parse_args()
    ds, _, _ = Kubectl(args.kubectl).snapshot()
    annotations = ds['metadata'].get('annotations', {})
    print(encoded({'daemonset_uid': ds['metadata']['uid'],
                   'resource_version': ds['metadata']['resourceVersion'],
                   'kured_lock': annotations.get(LOCK),
                   'maintenance_journal': annotations.get(JOURNAL)}))


if __name__ == '__main__':
    main()
