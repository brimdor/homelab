"""UID-scoped runtime annotation qualification on the zero-Pod fixture only."""

import hashlib
import json
import re

from maintenance_coordination import LOCK, JOURNAL, encoded, require


NAMESPACE = 'maintenance-qualification-103'
NAME = 'kured-owner-fixture'
LABEL = 'homelab.eaglepass.io/qualification'
REVISION = 'homelab.eaglepass.io/qualification-revision'


class Fixture:
    """The supplied adapter may read/patch only this dedicated qualification target."""

    def __init__(self, api, namespace_uid, daemonset_uid, spec_sha256):
        require(bool(namespace_uid) and bool(daemonset_uid) and
                isinstance(spec_sha256, str) and re.fullmatch('[0-9a-f]{64}', spec_sha256),
                'exact fixture identities required')
        self.api, self.namespace_uid, self.uid = api, namespace_uid, daemonset_uid
        self.spec_sha256 = spec_sha256

    def observed(self, revision):
        value = self.api.snapshot()
        ns, ds = value['namespace'], value['daemonset']
        require(ns['metadata']['name'] == NAMESPACE and ns['metadata']['uid'] == self.namespace_uid and
                ns['metadata'].get('labels', {}).get(LABEL) == 'maintenance-103' and
                not ns['metadata'].get('deletionTimestamp'), 'fixture namespace changed')
        require(ds['metadata']['name'] == NAME and ds['metadata']['namespace'] == NAMESPACE and
                ds['metadata']['uid'] == self.uid and not ds['metadata'].get('deletionTimestamp') and
                ds['metadata'].get('labels', {}).get(LABEL) == 'maintenance-103' and
                ds['metadata'].get('annotations', {}).get(REVISION) == revision and
                hashlib.sha256(encoded(ds['spec']).encode()).hexdigest() == self.spec_sha256,
                'fixture desired state changed')
        status = ds['status']
        require(status.get('observedGeneration') == ds['metadata']['generation'] and all(
            status.get(k, 0) == 0 for k in ('desiredNumberScheduled', 'currentNumberScheduled',
            'numberReady', 'numberAvailable', 'updatedNumberScheduled', 'numberMisscheduled')) and
            not value['pods'] and not value['pvcs'], 'fixture must have no Pods or data')
        require(not any(n['metadata'].get('labels', {}).get(
            'homelab.eaglepass.io/qualification-103') == 'never' for n in value['nodes']),
            'fixture has an eligible Node')
        require(value['quota']['metadata']['namespace'] == NAMESPACE and
                value['quota']['metadata']['name'] == 'no-pods' and
                value['quota']['spec']['hard'] == {'pods': '0'}, 'fixture Pod prohibition changed')
        return ds

    @staticmethod
    def owner(lock, journal):
        left, right = json.loads(lock), json.loads(journal)
        require(isinstance(left, dict) and isinstance(right, dict) and
                isinstance(left.get('nodeID'), str) and re.fullmatch(
                    'fixture-owner-103-[0-9a-f-]{36}', left['nodeID']) and
                left.get('metadata') == {'unschedulable': True} and
                type(left.get('TTL')) is int and left['TTL'] == 0 and
                right.get('owner') == left['nodeID'] and right.get('fixture') is True and
                right.get('created') == left.get('created'), 'invalid synthetic owner')

    def claim(self, lock, journal):
        self.owner(lock, journal)
        ds = self.observed('first')
        annotations = ds['metadata'].get('annotations', {})
        require(LOCK not in annotations and JOURNAL not in annotations, 'fixture already owned')
        operations = self.preconditions(ds)
        for key, value in ((LOCK, lock), (JOURNAL, journal)):
            operations.append({'op': 'add', 'path': self.pointer(key), 'value': value})
        self.api.patch(operations)
        return self.resume(lock, journal, 'first')

    def resume(self, lock, journal, revision):
        self.owner(lock, journal)
        ds = self.observed(revision)
        annotations = ds['metadata']['annotations']
        require(annotations.get(LOCK) == lock and annotations.get(JOURNAL) == journal,
                'exact fixture runtime owner differs')
        return ds

    def release(self, lock, journal):
        ds = self.resume(lock, journal, 'second')
        operations = self.preconditions(ds)
        for key, value in ((LOCK, lock), (JOURNAL, journal)):
            operations.extend([{'op': 'test', 'path': self.pointer(key), 'value': value},
                               {'op': 'remove', 'path': self.pointer(key)}])
        self.api.patch(operations)
        ds = self.observed('second')
        require(LOCK not in ds['metadata']['annotations'] and JOURNAL not in ds['metadata']['annotations'],
                'fixture release uncertain; observe before retry')
        return ds

    @staticmethod
    def pointer(key):
        return '/metadata/annotations/' + key.replace('~', '~0').replace('/', '~1')

    @staticmethod
    def preconditions(ds):
        return [{'op': 'test', 'path': '/metadata/uid', 'value': ds['metadata']['uid']},
                {'op': 'test', 'path': '/metadata/resourceVersion', 'value': ds['metadata']['resourceVersion']}]
