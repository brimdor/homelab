#!/usr/bin/env python3
"""Run the published synthetic AOF metadata/stream tests on existing Pikachu."""

import argparse
import json
from pathlib import Path
import shlex
import subprocess

import gitea_recovery_transport as transport


BOOT = '''import io,json,os,shutil,signal,sys,tempfile,types,unittest
request=json.load(sys.stdin)
for name,source in request['sources'].items():
 module=types.ModuleType(name);module.__file__='/repository/metal/scripts/'+name+'.py';sys.modules[name]=module
 if name=='pointguide_files_recovery':module.PROFILE_DATA=request['profiles']
 exec(compile(source,module.__file__,'exec'),module.__dict__)
common=sys.modules['etcd_recovery'];common.require_host('pikachu');common.private_root()
common.run_identifier(request['run_id']);original=common.ROOT
scratch=original/tempfile.mkdtemp(prefix=request['run_id']+'-aof-synthetic-',dir=original).split('/')[-1]
def interrupted(_number,_frame):raise RuntimeError('owned AOF qualification interrupted')
for number in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(number,interrupted)
try:
 common.ROOT=scratch
 suite=unittest.defaultTestLoader.loadTestsFromModule(sys.modules['test_valkey_source_aof'])
 result=unittest.TextTestRunner(stream=io.StringIO()).run(suite)
 summary={'accepted':result.wasSuccessful() and not result.skipped,'native_tests':result.testsRun,
  'errors':len(result.errors),'failures':len(result.failures),'skipped':len(result.skipped),'synthetic_only':True}
finally:
 common.ROOT=original
 shutil.rmtree(scratch)
 summary_cleanup={'scratch_absent':not scratch.exists(),'no_containers_or_images_created':True}
summary['cleanup']=summary_cleanup
print(json.dumps(summary),flush=True)
sys.exit(0 if summary['accepted'] else 1)
'''


def run(revision, run_id):
    root = Path(__file__).resolve().parents[2]
    transport.common.run_identifier(run_id)
    bundle = transport.Bundle(root, revision, {'pikachu': '10.0.20.14'})
    for name in ('gitea_recovery_transport', 'qualify_valkey_source_aof', 'test_valkey_cohort_point', 'test_valkey_source_aof'):
        bundle.sources[name] = bundle.exact(root, revision, 'metal/scripts/' + name + '.py').decode()
    response = subprocess.run([*transport.common.SSH, 'python3', '-I', '-B', '-c', shlex.quote(BOOT)],
        input=json.dumps({'sources': bundle.sources, 'profiles': bundle.profiles, 'run_id': run_id}).encode(),
        capture_output=True)
    if response.stderr:
        raise RuntimeError('native synthetic AOF qualification failed; raw output withheld')
    result = json.loads(response.stdout)
    if response.returncode or not result.get('accepted'):
        raise RuntimeError('native synthetic AOF tests refused acceptance: ' + json.dumps(result))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.revision, args.run_id)), flush=True)
