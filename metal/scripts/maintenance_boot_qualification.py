#!/usr/bin/env python3
"""Require fresh post-boot Kured status before the combined resume operation."""

from datetime import datetime
from pathlib import Path

import maintenance_combined_diagnostics as diagnostic
import maintenance_coordination as coordination


RESUME = 'ready();value=context();ownership,hold,hop=connected(value);'


def fresh_boot(ds, pods, nodes, expected, boot_id, boot_started):
    coordination.require(ds['metadata']['uid'] == expected['daemonset_uid'] and
                         {n['metadata']['name']: n['metadata']['uid'] for n in nodes} == expected['node_uids'],
                         'post-boot controller or node identity changed')
    if len(nodes) != 1 or nodes[0].get('status', {}).get('nodeInfo', {}).get('bootID') != boot_id:
        return False
    health = {c['type']: c['status'] for c in nodes[0].get('status', {}).get('conditions', [])}
    if health.get('Ready') != 'True' or any(health.get(k) != 'False' for k in ('MemoryPressure', 'DiskPressure', 'PIDPressure')):
        return False
    if not coordination.rollout_ready(ds['metadata'], ds.get('status', {}), 1):
        return False
    if len(pods) != 1:
        return False
    pod = pods[0]
    coordination.require(any(o.get('uid') == expected['daemonset_uid'] and o.get('controller') is True
                             for o in pod['metadata'].get('ownerReferences', [])),
                         'post-boot Kured Pod owner changed')
    status = pod.get('status', {})
    conditions = {c['type']: c['status'] for c in status.get('conditions', [])}
    containers = status.get('containerStatuses', [])
    if (pod['metadata'].get('deletionTimestamp') or pod['spec'].get('nodeName') not in expected['node_uids'] or
            status.get('phase') != 'Running' or
            any(conditions.get(k) != 'True' for k in ('PodReadyToStartContainers', 'ContainersReady', 'Ready')) or
            len(containers) != 1):
        return False
    container = containers[0]
    if container.get('name') != 'kured' or container.get('ready') is not True:
        return False
    running = container.get('state', {}).get('running', {})
    try:
        started = datetime.fromisoformat(running['startedAt'].replace('Z', '+00:00'))
        if started.utcoffset() is None or started.timestamp() < boot_started:
            return False
    except (KeyError, TypeError, ValueError):
        return False
    # Reuse every runtime, image, node-health and ownership guard after freshness.
    class Snapshot:
        def snapshot(self):
            return ds, pods, nodes
    coordination.Ownership(Snapshot(), expected['daemonset_uid'], expected['node_uids']).observed()
    return True


RUNTIME = '''
import types
boot_module=types.ModuleType('maintenance_boot_qualification')
boot_module.__file__='/ram/maintenance_boot_qualification.py'
# Only the pure predicate is loaded; the host-only subclass stays on the controller.
exec(compile(boot_predicate,boot_module.__file__,'exec'),boot_module.__dict__)
def post_boot_ready(value):
 end=time.monotonic()+900
 ready()
 boot_id=pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
 boot_started=int(next(line.split()[1]for line in pathlib.Path('/proc/stat').read_text().splitlines()if line.startswith('btime ')))
 while True:
  ds,pods,nodes=api.snapshot()
  if boot_module.fresh_boot(ds,pods,nodes,value,boot_id,boot_started):
   evidence={'boot_id':boot_id,'boot_started':boot_started,'node_uid':nodes[0]['metadata']['uid'],
             'pod_uid':pods[0]['metadata']['uid'],'container_started_at':pods[0]['status']['containerStatuses'][0]['state']['running']['startedAt'],
             'current_boot_node_and_ready_container':True}
   actors.exclusive_file(actors.STATE/'boot-readiness.json',json.dumps(evidence,sort_keys=True).encode(),0o600)
   return
  if time.monotonic()>end:raise RuntimeError('current-boot Kured did not become ready')
  time.sleep(2)
'''


class Qualification(diagnostic.Qualification):
    def guest(self, body, expected=0):
        if RESUME not in body:
            return super().guest(body, expected)
        if body.count(RESUME) != 1 or expected != 0:
            raise RuntimeError('combined resume entry changed')
        source = Path(__file__).read_text()
        predicate = ('from datetime import datetime\nimport maintenance_coordination as coordination\n' +
                     source[source.index('def fresh_boot('):source.index('\n\nRUNTIME =')])
        program = ('boot_predicate=' + repr(predicate) + '\n' + RUNTIME + '\n' +
                   body.replace(RESUME, 'value=context();post_boot_ready(value);ownership,hold,hop=connected(value);', 1))
        result = super().guest(program, expected)
        result['boot_readiness'] = super().guest(
            "print(json.dumps(json.loads((actors.STATE/'boot-readiness.json').read_text())))")
        return result


if __name__ == '__main__':
    diagnostic.main(Qualification)
