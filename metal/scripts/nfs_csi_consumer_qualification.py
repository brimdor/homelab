#!/usr/bin/env python3
"""Measure current NFS consumer identities and cache options on synthetic data."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import time

import nfs_csi_qualification as nfs


def consumer_manifest(cluster, claim, name, node, uid, fs_group=None):
    security = {'runAsUser': uid, 'runAsGroup': uid, 'runAsNonRoot': uid != 0,
                'seccompProfile': {'type': 'RuntimeDefault'}}
    if fs_group is not None:
        security.update(fsGroup=fs_group, fsGroupChangePolicy='OnRootMismatch')
    return {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': nfs.NAMESPACE},
            'spec': {'nodeName': 'k3d-' + cluster + '-agent-' + str(node), 'restartPolicy': 'Never',
                     'automountServiceAccountToken': False, 'securityContext': security,
                     'containers': [{'name': 'client', 'image': nfs.CLIENT,
                                     'command': ['python3', '-c', 'import time;time.sleep(2147483647)'],
                                     'securityContext': {'readOnlyRootFilesystem': True,
                                                         'allowPrivilegeEscalation': False,
                                                         'capabilities': {'drop': ['ALL']}},
                                     'volumeMounts': [{'name': 'data', 'mountPath': '/data'}]}],
                     'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': claim}}]}}


def require_consumer_mount(records, version):
    nfs.require_mount(records, version)
    if (not {'hard', 'nosharecache', 'local_lock=none'} <= set(records[0]['options'].split(',')) or
            not re.fullmatch(r'\d+:\d+', records[0].get('device', ''))):
        raise RuntimeError('consumer mount lacks exact cache/remote-lock/superblock evidence')


class Qualification(nfs.Qualification):
    def path(self, name):
        if not re.fullmatch(r'consumer-(?:3|4-1)-(?:builder|mismatch|backup)', name):
            raise RuntimeError('unowned synthetic consumer directory')
        return self.export + '/' + name

    def prepare(self, name, uid, gid, mode):
        path = self.path(name)
        self.guest('sudo', 'python3', '-c',
                   "import os,sys;from pathlib import Path\n"
                   "p=Path(sys.argv[1]);p.mkdir(mode=int(sys.argv[4],8));"
                   "os.chown(p,int(sys.argv[2]),int(sys.argv[3]));os.chmod(p,int(sys.argv[4],8));"
                   "f=p/'marker';f.write_bytes(b'qualification-marker\\n');"
                   "os.chown(f,int(sys.argv[2]),int(sys.argv[3]));os.chmod(f,0o600)",
                   path, str(uid), str(gid), mode)
        return self.snapshot(name)

    def snapshot(self, name):
        return json.loads(self.guest('sudo', 'python3', '-c',
                          "import os,sys,stat,json,hashlib;from pathlib import Path\n"
                          "p=Path(sys.argv[1]);out={}\n"
                          "for name in ('','marker'):\n"
                          " f=p/name;s=f.stat();out[name]={'uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode)}\n"
                          " if f.is_file():out[name]['sha256']=hashlib.sha256(f.read_bytes()).hexdigest()\n"
                          "print(json.dumps(out))", self.path(name)))

    def binding(self, name, directory, version):
        path = self.path(directory)
        share = path if version == '3' else '/' + directory
        self.apply({'apiVersion': 'v1', 'kind': 'PersistentVolume', 'metadata': {'name': name},
                    'spec': {'storageClassName': '', 'capacity': {'storage': '1Mi'},
                             'accessModes': ['ReadWriteMany'], 'persistentVolumeReclaimPolicy': 'Retain',
                             'mountOptions': ['nfsvers=' + version, 'hard', 'nosharecache'],
                             'claimRef': {'namespace': nfs.NAMESPACE, 'name': name},
                             'csi': {'driver': 'nfs.csi.k8s.io', 'volumeHandle': name,
                                     'volumeAttributes': {'server': nfs.SERVER, 'share': share,
                                                          'mountPermissions': '0'}}}},
                   {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim',
                    'metadata': {'name': name, 'namespace': nfs.NAMESPACE},
                    'spec': {'storageClassName': '', 'volumeName': name, 'accessModes': ['ReadWriteMany'],
                             'resources': {'requests': {'storage': '1Mi'}}}})
        self.kubectl('wait', '--for=jsonpath={.status.phase}=Bound', 'pvc/' + name, '-n', nfs.NAMESPACE,
                     '--timeout=120s', json_output=False)
        claim = self.kubectl('get', 'pvc', name, '-n', nfs.NAMESPACE)
        pv = self.kubectl('get', 'pv', name)
        nfs.require_pv(pv, claim, share)
        if (pv['spec']['persistentVolumeReclaimPolicy'] != 'Retain' or
                pv['spec']['csi']['volumeAttributes']['mountPermissions'] != '0'):
            raise RuntimeError('synthetic static retention/permissions contract changed')
        return name

    def consumer(self, claim, name, node, uid, fs_group=None, *, wait=True):
        self.apply(consumer_manifest(self.args.name, claim, name, node, uid, fs_group))
        if wait:
            self.kubectl('wait', '--for=condition=Ready', 'pod/' + name, '-n', nfs.NAMESPACE,
                         '--timeout=180s', json_output=False)
        return name

    def mount(self, pod, version):
        result = self.execute(pod, "import json;out=[]\nfor l in open('/proc/self/mountinfo'):\n a,b=l.split(' - ');x=a.split();y=b.split()\n if x[4]=='/data':out.append({'filesystem':y[0],'source':y[1],'options':y[2],'device':x[2]})\nprint(json.dumps(out))")
        require_consumer_mount(result, version)
        return result

    def mismatch(self, directory, version):
        before = self.prepare(directory, 0, 0, '0755')
        claim = self.binding(directory, directory, version)
        pod = self.consumer(claim, 'mismatched-builder', 0, 1000, 1000, wait=False)
        observed = None
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            value = self.kubectl('get', 'pod', pod, '-n', nfs.NAMESPACE)
            if any(c.get('type') == 'Ready' and c.get('status') == 'True'
                   for c in value.get('status', {}).get('conditions', [])):
                denied = self.execute(pod, "import json\ntry:open('/data/forbidden','xb')\nexcept PermissionError:print(json.dumps(True))\nelse:raise RuntimeError('incompatible synthetic ownership unexpectedly admitted writes')")
                if denied is not True:
                    raise RuntimeError('incompatible ownership did not deny application writes')
                observed = {'pod_ready': True, 'application_write_denied': True,
                            'mount': self.mount(pod, version)}
                break
            events = self.kubectl('get', 'events', '-n', nfs.NAMESPACE)['items']
            failures = [e for e in events if e.get('involvedObject', {}).get('uid') == value['metadata']['uid']
                        and e.get('reason') == 'FailedMount' and
                        re.search(r'(?i)(permission denied|operation not permitted)', e.get('message', ''))]
            if failures:
                observed = {'pod_ready': False, 'mount_permission_failure': True,
                            'event_message_sha256': [hashlib.sha256(e['message'].encode()).hexdigest()
                                                     for e in failures]}
                break
            time.sleep(2)
        if observed is None:
            raise RuntimeError('incompatible ownership outcome was not established')
        self.remove_pods(pod)
        if self.snapshot(directory) != before:
            raise RuntimeError('mismatched synthetic directory metadata unexpectedly changed')
        return observed | {'existing_metadata_unchanged': True}

    def consumers(self, version):
        stem = 'consumer-' + version.replace('.', '-')
        directory = stem + '-builder'
        self.prepare(directory, 1000, 1000, '2770')
        # Keep a root-owned directory with the correct group; OnRootMismatch must skip traversal.
        self.guest('sudo', 'chown', '0:1000', self.path(directory))
        self.guest('sudo', 'chmod', '2770', self.path(directory))
        before = self.snapshot(directory)
        if before[''] != {'uid': 0, 'gid': 1000, 'mode': 0o2770}:
            raise RuntimeError('prepared Builder directory metadata differs from the reviewed profile')
        claims = [self.binding(stem + '-binding-' + str(n), directory, version) for n in (0, 1)]
        pods = [self.consumer(claims[n % 2], 'builder-' + str(n), n // 2, 1000, 1000) for n in range(3)]
        mounts = [self.mount(pod, version) for pod in pods]
        if mounts[0][0]['device'] == mounts[1][0]['device']:
            raise RuntimeError('same-node NFS aliases did not establish independent superblocks')
        if self.snapshot(directory) != before:
            raise RuntimeError('OnRootMismatch changed existing synthetic metadata')
        self.lock_exclusion(pods[:2])
        self.lock_exclusion([pods[0], pods[2]])
        def write(pod):
            return self.execute(pod, "import fcntl,os,json,time\nwith open('/data/shared','a') as f:\n for n in range(100):\n  fcntl.flock(f,fcntl.LOCK_EX);f.write(" + repr(pod) + "+':'+str(n)+'\\n');f.flush();os.fsync(f.fileno());fcntl.flock(f,fcntl.LOCK_UN);time.sleep(.005)\nprint(json.dumps(os.getuid()))")
        with ThreadPoolExecutor(max_workers=3) as pool:
            if list(pool.map(write, pods)) != [1000] * 3:
                raise RuntimeError('synthetic consumer writer identity changed')
        verify = "import os,json,hashlib\nb=open('/data/shared','rb').read();s=os.stat('/data/shared');lines=b.decode().splitlines();assert len(lines)==300 and set(lines)=={p+':'+str(n) for p in ['builder-0','builder-1','builder-2'] for n in range(100)};assert s.st_uid==1000 and s.st_gid==1000;print(json.dumps({'sha256':hashlib.sha256(b).hexdigest(),'lines':len(lines),'uid':s.st_uid,'gid':s.st_gid}))"
        corpus = [self.execute(pod, verify) for pod in pods]
        if corpus[1:] != corpus[:1] * 2:
            raise RuntimeError('independent cache aliases disagree on complete consumer corpus')
        self.remove_pods(*pods)
        restored = self.consumer(claims[0], 'recreated-builder', 0, 1000, 1000)
        if self.execute(restored, verify) != corpus[0] or self.snapshot(directory) != before:
            raise RuntimeError('consumer recreation changed data or original metadata')
        self.remove_pods(restored)
        incompatible = self.mismatch(stem + '-mismatch', version)
        backup = stem + '-backup'
        backup_before = self.prepare(backup, 65534, 65534, '2770')
        backup_claim = self.binding(backup, backup, version)
        root = self.consumer(backup_claim, 'root-backup', 1, 0)
        root_mount = self.mount(root, version)
        owner = self.execute(root, "import os,json;open('/data/backup-probe','xb').write(b'synthetic');s=os.stat('/data/backup-probe');print(json.dumps([s.st_uid,s.st_gid]))")
        if owner != [65534, 65534] or self.snapshot(backup) != backup_before:
            raise RuntimeError('root backup consumer squash/metadata contract changed')
        self.remove_pods(root)
        self.persist('consumers-' + version, builder_fsGroup=1000, fsGroupChangePolicy='OnRootMismatch',
                     same_node_distinct_superblocks=True, same_and_cross_node_lock_exclusion=True,
                     mounts=mounts, corpus=corpus[0], recreation=True, existing_metadata_unchanged=True,
                     incompatible_ownership=incompatible, root_backup_mount=root_mount,
                     root_backup_owner=owner, synthetic_directory_modes='2770; mismatch0755')

    def run(self):
        self.create()
        self.server()
        self.install()
        self.consumers('4.1')
        self.status_monitors()
        self.consumers('3')
        return {'accepted': True, 'stages': self.stages, 'production_change': False,
                'scope': 'synthetic-current-consumer-identities-and-nosharecache',
                'production_nas_and_amd64_fedora_kernel_unqualified': True,
                'general_nosharecache_coherence_not_proven': True,
                'backup_commands_and_real_data_not_tested': True}


if __name__ == '__main__':
    nfs.main(Qualification)
