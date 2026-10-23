#!/usr/bin/env python3
"""Retain readiness evidence when the unchanged combined fixture refuses."""

import argparse
import json
from pathlib import Path
import signal

import maintenance_combined_qualification as combined


DIAGNOSTIC = '''
def selected(command):
 result=subprocess.run(command,capture_output=True)
 if result.returncode:
  return {'exit':result.returncode,'security_refusal':any(word in result.stderr.lower()for word in(b'unauthorized',b'forbidden',b'x509',b'certificate'))}
 return json.loads(result.stdout)
prefix=['/usr/local/bin/qualification-kubectl','--request-timeout=30s']
ds=selected(prefix+['get','daemonset','kured','-n','kured','-o','json'])
pods=selected(prefix+['get','pods','-n','kured','-o','json'])
events=selected(prefix+['get','events','-n','kured','-o','json'])
out={'selinux_enforcing':pathlib.Path('/sys/fs/selinux/enforce').read_text().strip(),
     'cpu_pressure':pathlib.Path('/proc/pressure/cpu').read_text().splitlines(),
     'uptime':pathlib.Path('/proc/uptime').read_text().strip()}
out['daemonset']={'uid':ds['metadata']['uid'],'generation':ds['metadata']['generation'],'status':ds.get('status',{})}if'metadata'in ds else ds
out['pods']=[]
for pod in pods.get('items',[]):
 status=pod.get('status',{})
 containers=[]
 for container in status.get('containerStatuses',[]):
  states={kind:{key:value for key,value in state.items()if key in('reason','exitCode','signal','startedAt','finishedAt')}for kind,state in container.get('state',{}).items()}
  containers.append({'name':container['name'],'ready':container['ready'],'restartCount':container['restartCount'],'state':states})
 out['pods'].append({'uid':pod['metadata']['uid'],'phase':status.get('phase'),
  'conditions':[{key:value for key,value in condition.items()if key in('type','status','reason','lastTransitionTime')}for condition in status.get('conditions',[])],
  'containers':containers})
if'exit'in pods:out['pod_read_failure']=pods
uids={pod['uid']for pod in out['pods']}
out['events']=[]
for event in events.get('items',[]):
 if event.get('type')!='Warning' or event.get('involvedObject',{}).get('uid')not in uids:continue
 message=event.get('message','')
 safe=not re.search(r'token|password|secret|credential|authorization|private.key',message,re.I)
 out['events'].append({'reason':event.get('reason'),'uid':event['involvedObject']['uid'],'count':event.get('count'),
  'lastTimestamp':event.get('lastTimestamp'),'message_sha256':hashlib.sha256(message.encode()).hexdigest(),
  'safe_message':message[:1000]if safe else '[redacted]'})
if'exit'in events:out['event_read_failure']=events
logs=subprocess.run(['journalctl','--no-pager','--output=cat','-n','500'],capture_output=True)
out['safe_avc_lines']=[line[:1000]for line in logs.stdout.decode(errors='replace').splitlines()if re.search(r'avc:.*denied',line,re.I)and not re.search(r'token|password|secret|credential|authorization|private.key',line,re.I)][-20:]
print(json.dumps(out))
'''


class Qualification(combined.Qualification):
    def guest(self, body, expected=0):
        try:
            return super().guest(body, expected)
        except Exception:
            # Observe only; never replay a refused journal or ownership operation.
            try:
                evidence = super().guest(DIAGNOSTIC)
            except Exception as error:
                evidence = {'diagnostic_failed': type(error).__name__}
            (self.root / 'readiness-failure.json').write_text(json.dumps(evidence, indent=2))
            raise


def main(qualification_class=Qualification):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('work-dir', 'cloud-image', 'server-image', 'ansible-playbook', 'collection-dir',
                 'automatic-rpm', 'k3s-binary', 'airgap-images', 'kured-archive', 'selinux-rpm', 'selinux-key'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--qemu', default='qemu-system-x86_64')
    parser.add_argument('--qemu-img', default='qemu-img')
    qualification = qualification_class(parser.parse_args())
    def cancel(_number, _frame):
        raise RuntimeError('owned diagnostic qualification cancelled')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(number, cancel)
    try:
        result = qualification.run()
        (qualification.root / 'combined-result.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result), flush=True)
    finally:
        qualification.cleanup()


if __name__ == '__main__':
    main()
