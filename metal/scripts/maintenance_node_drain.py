"""UID-bound serial evictions; observe an uncertain request, never replay it."""

import json
import os
import re
import stat

import maintenance_actor_hold as actor
import maintenance_hop_journal as hops


CONTROLLERS = {'DaemonSet': 'daemonset', 'ReplicaSet': 'replicaset',
               'StatefulSet': 'statefulset', 'Job': 'job',
               'ReplicationController': 'replicationcontroller', 'Node': 'node'}


def hashed(value):
    return hops.digest(hops.canonical(value))


def name(value):
    actor.require(isinstance(value, str) and len(value) <= 253 and re.fullmatch(
        r'[a-z0-9](?:[-a-z0-9.]*[a-z0-9])?', value), 'unsafe drain resource name')
    return value


def private_json(path):
    actor.safe(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as source:
        before = os.fstat(source.fileno())
        actor.require(stat.S_ISREG(before.st_mode) and before.st_uid == os.geteuid() and
                      stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1 and
                      0 < before.st_size < 8 * 1024 * 1024, 'unsafe drain record')
        raw = source.read()
        after = os.fstat(source.fileno())
    actor.require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
                  (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
                  'drain record changed during read')
    value = json.loads(raw)
    actor.require(isinstance(value, dict) and raw == hops.canonical(value), 'noncanonical drain record')
    return value


class Drain:
    def __init__(self, journal, api):
        self.journal, self.api = journal, api
        self.parent = journal.hold.state / 'drains'
        self.path = self.parent / journal.token

    def inventory(self, allow_terminating=()):
        owner = self.journal.owners()['global']
        node = self.api.call('get', 'node', name(owner['node']), '-o', 'json')
        actor.require(node['metadata']['uid'] == owner['node_uid'] and
                      not node['metadata'].get('deletionTimestamp') and
                      node['spec'].get('unschedulable') is True, 'drain Node identity or cordon differs')
        pods = self.api.call('get', 'pods', '-A', '--field-selector',
                             'spec.nodeName=' + owner['node'], '-o', 'json')['items']
        batch = getattr(self.api, 'drain_controllers', None)
        controllers_by_identity = batch() if batch is not None else None
        refs = []
        for pod in pods:
            metadata = pod['metadata']
            namespace, pod_name = name(metadata['namespace']), name(metadata['name'])
            actor.require(pod['spec']['nodeName'] == owner['node'] and
                          isinstance(metadata.get('uid'), str) and metadata['uid'] and
                          (not metadata.get('deletionTimestamp') or metadata['uid'] in allow_terminating),
                          'drain Pod identity or deletion differs')
            controllers = [o for o in metadata.get('ownerReferences', []) if o.get('controller') is True]
            actor.require(len(controllers) == 1, 'drain Pod lacks one exact controller')
            controller = controllers[0]
            kind = controller.get('kind')
            actor.require(kind in CONTROLLERS and isinstance(controller.get('uid'), str) and
                          controller['uid'] and controller.get('apiVersion') in
                          ('v1', 'apps/v1', 'batch/v1'), 'unreviewed drain Pod controller')
            argv = ['get', CONTROLLERS[kind], name(controller['name'])]
            if kind != 'Node':
                argv += ['-n', namespace]
            if controllers_by_identity is not None and kind != 'Node':
                actual = controllers_by_identity.get((kind, namespace, controller['name']))
                actor.require(actual is not None, 'drain controller absent from fresh inventory')
            else:
                actual = self.api.call(*argv, '-o', 'json')
            actor.require(actual['metadata']['uid'] == controller['uid'] and
                          actual.get('kind') == kind and actual.get('apiVersion') == controller['apiVersion'] and
                          not actual['metadata'].get('deletionTimestamp'), 'drain controller identity differs')
            mirror = 'kubernetes.io/config.mirror' in metadata.get('annotations', {})
            actor.require(not mirror or isinstance(metadata['annotations']['kubernetes.io/config.mirror'], str) and
                          metadata['annotations']['kubernetes.io/config.mirror'], 'empty mirror Pod identity')
            actor.require(kind != 'Node' or mirror and controller['uid'] == owner['node_uid'],
                          'foreign non-mirror Node-owned Pod')
            actor.require(not mirror or kind == 'Node', 'mirror Pod controller differs')
            refs.append({'namespace': namespace, 'name': pod_name, 'uid': metadata['uid'],
                         'spec_sha256': hashed(pod['spec']), 'controller': controller,
                         'keep': kind in ('DaemonSet', 'Node')})
        refs.sort(key=lambda ref: (ref['namespace'], ref['name'], ref['uid']))
        actor.require(len({ref['uid'] for ref in refs}) == len(refs) and
                      len({(ref['namespace'], ref['name']) for ref in refs}) == len(refs),
                      'duplicate drain Pod identity')
        return {'node': owner['node'], 'node_uid': owner['node_uid'], 'pods': refs}

    def start(self, reviewed_plan, reviewed_sha256, prerequisites_sha256, verify_prerequisites):
        actor.require(hashed(reviewed_plan) == reviewed_sha256 and self.inventory() == reviewed_plan,
                      'drain plan differs from reviewed inventory')
        self.journal.begin('drain', reviewed_sha256, prerequisites_sha256, verify_prerequisites)
        return self.attach(reviewed_plan)

    def attach(self, reviewed_plan):
        """Attach only the exact committed plan; never repeat the parent begin."""
        with self.journal.hold.serialized():
            state = self.journal.read()
            actor.require(state['pending'] and state['pending']['step'] == 'drain',
                          'exact pending drain intent missing')
            intent_path = self.journal.path / (str(state['pending']['sequence']).zfill(8) + '.json')
            intent = private_json(intent_path)
            actor.require(intent['inputs_sha256'] == hashed(reviewed_plan), 'pending drain plan differs')
            header = {'version': 1, 'owners': state['owners'], 'intent': state['pending'], 'plan': reviewed_plan}
            if self.path.exists() and (self.path / 'header.json').exists():
                actor.require(self.header() == header, 'existing drain header differs')
            else:
                actor.require(self.inventory() == reviewed_plan, 'unstarted drain inventory changed')
                if not self.parent.exists():
                    actor.safe(self.parent);self.parent.mkdir(mode=0o700);actor.fsync_directory(self.parent.parent)
                hops.private_directory(self.parent)
                actor.safe(self.path)
                if not self.path.exists():
                    self.path.mkdir(mode=0o700);actor.fsync_directory(self.parent)
                hops.private_directory(self.path)
                actor.require(not any(self.path.iterdir()), 'foreign incomplete drain directory')
                actor.exclusive_file(self.path / 'header.json', hops.canonical(header), 0o600)
            return self.read()

    def header(self):
        hops.private_directory(self.parent);hops.private_directory(self.path)
        return private_json(self.path / 'header.json')

    def read(self):
        state, header = self.journal.read(), self.header()
        actor.require(set(header) == {'version', 'owners', 'intent', 'plan'} and
                      type(header['version']) is int and header['version'] == 1 and
                      header['owners'] == state['owners'] and header['intent'] == state['pending'] and
                      state['pending'] and state['pending']['step'] == 'drain', 'drain owner or parent intent differs')
        intent_path = self.journal.path / (str(state['pending']['sequence']).zfill(8) + '.json')
        actor.require(private_json(intent_path)['inputs_sha256'] == hashed(header['plan']),
                      'drain header plan differs from committed intent')
        targets = [ref for ref in header['plan']['pods'] if not ref['keep']]
        expected, completed, pending = {'header.json'}, [], None
        hashes = {'header.json': hashed(header)}
        for index, ref in enumerate(targets):
            prefix = str(index).zfill(8)
            intent_name, observed_name = prefix + '.intent.json', prefix + '.observed.json'
            if not (self.path / intent_name).exists():
                break
            value = private_json(self.path / intent_name)
            actor.require(set(value) == {'version', 'parent', 'index', 'pod', 'resource_version',
                                        'prerequisites_sha256'} and
                          type(value['version']) is int and value['version'] == 1 and
                          type(value['index']) is int and value['index'] == index and
                          value['parent'] == state['pending']['sha256'] and value['pod'] == ref and
                          isinstance(value['resource_version'], str) and value['resource_version'] and
                          hops.checksum(value['prerequisites_sha256']), 'invalid eviction intent')
            expected.add(intent_name)
            hashes[intent_name] = hashed(value)
            dispatch_name = prefix + '.first-dispatch.json'
            if (self.path / dispatch_name).exists():
                dispatch = private_json(self.path / dispatch_name)
                actor.require(set(dispatch) == {'version', 'intent_sha256', 'failure_sha256',
                                               'resource_version', 'prerequisites_sha256'} and
                              type(dispatch['version']) is int and dispatch['version'] == 1 and
                              dispatch['intent_sha256'] == hashed(value) and
                              hops.checksum(dispatch['failure_sha256']) and
                              hops.checksum(dispatch['prerequisites_sha256']) and
                              isinstance(dispatch['resource_version'], str) and dispatch['resource_version'],
                              'invalid first-dispatch recovery record')
                expected.add(dispatch_name);hashes[dispatch_name] = hashed(dispatch)
            if not (self.path / observed_name).exists():
                pending = {'index': index, 'pod': ref, 'intent_sha256': hashed(value)}
                break
            observed = private_json(self.path / observed_name)
            actor.require(set(observed) == {'version', 'intent_sha256', 'pod_uid', 'inventory_sha256',
                                           'prerequisites_sha256'} and
                          type(observed['version']) is int and observed['version'] == 1 and
                          observed['intent_sha256'] == hashed(value) and observed['pod_uid'] == ref['uid'] and
                          hops.checksum(observed['inventory_sha256']) and
                          hops.checksum(observed['prerequisites_sha256']), 'invalid eviction observation')
            hashes[observed_name] = hashed(observed)
            expected.add(observed_name);completed.append(ref['uid'])
        actor.require({p.name for p in self.path.iterdir()} == expected, 'foreign or out-of-order drain record')
        return {'header': header, 'completed': completed, 'pending': pending, 'targets': targets,
                'records_sha256': hashed(hashes)}

    def advance(self, prerequisites_sha256, verify_prerequisites):
        actor.require(hops.checksum(prerequisites_sha256), 'invalid drain prerequisite digest')
        with self.journal.hold.serialized():
            state = self.read()
            allowed = (state['pending']['pod']['uid'],) if state['pending'] else ()
            current = self.inventory(allowed)
            original = state['header']['plan']
            by_uid = {ref['uid']: ref for ref in original['pods']}
            actor.require(current['node'] == original['node'] and current['node_uid'] == original['node_uid'] and
                          all(by_uid.get(ref['uid']) == ref for ref in current['pods']),
                          'new or changed target-node Pod during drain')
            present = {ref['uid'] for ref in current['pods']}
            actor.require(not present.intersection(state['completed']) and all(
                ref['uid'] in present for ref in original['pods'] if ref['keep']),
                'observed drained Pod returned or keep-set changed')
            pending = state['pending']
            if pending and pending['pod']['uid'] in present:
                return {'complete': False, 'pending': pending, 'mutation_performed': False}
            actor.require(verify_prerequisites('drain', prerequisites_sha256) is True,
                          'current drain prerequisites refused')
            actor.require(self.read() == state and self.inventory(allowed) == current,
                          'drain state changed during prerequisite verification')
            if pending:
                record = {'version': 1, 'intent_sha256': pending['intent_sha256'],
                          'pod_uid': pending['pod']['uid'], 'inventory_sha256': hashed(current),
                          'prerequisites_sha256': prerequisites_sha256}
                actor.exclusive_file(self.path / (str(pending['index']).zfill(8) + '.observed.json'),
                                     hops.canonical(record), 0o600)
                return {'complete': False, 'observed': record, 'mutation_performed': False}
            index = len(state['completed'])
            if index == len(state['targets']):
                actor.require(current['pods'] == [ref for ref in original['pods'] if ref['keep']],
                              'drain final keep-set differs')
                return {'complete': True, 'parent_intent': state['header']['intent'],
                        'plan_sha256': hashed(original), 'completed': state['completed'],
                        'inventory_sha256': hashed(current), 'records_sha256': state['records_sha256'],
                        'prerequisites_sha256': prerequisites_sha256, 'mutation_performed': False}
            ref = state['targets'][index]
            actor.require(ref['uid'] in present, 'unstarted eviction Pod disappeared; review required')
            pod = self.api.call('get', 'pod', ref['name'], '-n', ref['namespace'], '-o', 'json')
            actor.require(pod['metadata']['uid'] == ref['uid'] and not pod['metadata'].get('deletionTimestamp') and
                          hashed(pod['spec']) == ref['spec_sha256'] and
                          isinstance(pod['metadata'].get('resourceVersion'), str) and
                          pod['metadata']['resourceVersion'],
                          'eviction Pod identity, spec or version differs')
            record = {'version': 1, 'parent': state['header']['intent']['sha256'], 'index': index,
                      'pod': ref, 'resource_version': pod['metadata']['resourceVersion'],
                      'prerequisites_sha256': prerequisites_sha256}
            # Complete fallible prechecks before recording the dispatch intent.
            self.journal.owners(idle=True)
            actor.require(self.inventory() == current, 'drain inventory changed before durable intent')
            actor.exclusive_file(self.path / (str(index).zfill(8) + '.intent.json'), hops.canonical(record), 0o600)
            eviction = {'apiVersion': 'policy/v1', 'kind': 'Eviction',
                        'metadata': {'namespace': ref['namespace'], 'name': ref['name']},
                        'deleteOptions': {'preconditions': {'uid': ref['uid'],
                                                          'resourceVersion': pod['metadata']['resourceVersion']}}}
            endpoint = '/api/v1/namespaces/' + ref['namespace'] + '/pods/' + ref['name'] + '/eviction'
            result = self.api.call('create', '--raw=' + endpoint, '-f', '-', data=hops.canonical(eviction))
            actor.require(isinstance(result, dict) and result.get('kind') == 'Status' and
                          result.get('status') == 'Success', 'eviction response uncertain; observe, never replay')
            return {'complete': False, 'queued': ref, 'mutation_performed': True, 'accepted': False}

    def first_dispatch(self, intent_sha256, failure_sha256, prerequisites_sha256,
                       verify_not_dispatched, verify_prerequisites):
        """An exact captured pre-dispatch failure permits one first API request."""
        with self.journal.hold.serialized():
            state = self.read();pending = state['pending']
            actor.require(pending and pending['intent_sha256'] == intent_sha256 and
                          hops.checksum(failure_sha256) and
                          verify_not_dispatched(pending, failure_sha256) is True,
                          'definitive pre-dispatch evidence missing; observation only')
            self.journal.owners(idle=True)
            actor.require(verify_prerequisites('drain', prerequisites_sha256) is True,
                          'current drain prerequisites refused')
            current = self.inventory();ref = pending['pod']
            expected = [p for p in state['header']['plan']['pods'] if p['uid'] not in state['completed']]
            actor.require(current['pods'] == expected and self.read() == state,
                          'reviewed remaining drain inventory changed')
            pod = self.api.call('get', 'pod', ref['name'], '-n', ref['namespace'], '-o', 'json')
            actor.require(pod['metadata']['uid'] == ref['uid'] and not pod['metadata'].get('deletionTimestamp') and
                          hashed(pod['spec']) == ref['spec_sha256'], 'undispatched Pod identity changed')
            version = pod['metadata']['resourceVersion']
            record = {'version': 1, 'intent_sha256': intent_sha256, 'failure_sha256': failure_sha256,
                      'resource_version': version, 'prerequisites_sha256': prerequisites_sha256}
            # Exclusive creation prevents a second request after any uncertain outcome.
            actor.exclusive_file(self.path / (str(pending['index']).zfill(8) + '.first-dispatch.json'),
                                 hops.canonical(record), 0o600)
            eviction = {'apiVersion': 'policy/v1', 'kind': 'Eviction',
                        'metadata': {'namespace': ref['namespace'], 'name': ref['name']},
                        'deleteOptions': {'preconditions': {'uid': ref['uid'], 'resourceVersion': version}}}
            endpoint = '/api/v1/namespaces/' + ref['namespace'] + '/pods/' + ref['name'] + '/eviction'
            result = self.api.call('create', '--raw=' + endpoint, '-f', '-', data=hops.canonical(eviction))
            actor.require(result.get('kind') == 'Status' and result.get('status') == 'Success',
                          'first eviction dispatch uncertain; observe only')
            return {'queued': ref, 'first_dispatch': True, 'replayed': False}
