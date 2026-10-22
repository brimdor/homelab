"""Refuse unsafe multipart manifests and incomplete protected source streams."""

import copy
import hashlib
import io
import os
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import valkey_source_aof as aof
import qualify_valkey_source_aof as qualification
from test_valkey_cohort_point import binding, core


def fixture_stream(ordinal='0'):
    files = {'appendonly.aof.12.base.rdb':b'REDIS0012synthetic-only', 'appendonly.aof.12.incr.aof':b'',
        aof.MANIFEST:b'file appendonly.aof.12.base.rdb seq 12 type b\nfile appendonly.aof.12.incr.aof seq 12 type i\n'}
    header = {'format':aof.FORMAT, 'source':binding(ordinal), 'files':{name:{'bytes':len(raw),
        'sha256':hashlib.sha256(raw).hexdigest(), 'source_mode':0o664} for name,raw in files.items()}}
    encoded = aof.common.canonical(header)
    return header, encoded+b'\n'+b''.join(files[n] for n in sorted(files))+aof.common.canonical({'commit':hashlib.sha256(encoded).hexdigest()})+b'\n'


class SourceAofTests(unittest.TestCase):
    def test_native_qualification_frame_reaps_its_exact_synthetic_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            common_source=("from pathlib import Path\nROOT=Path("+repr(temporary)+")\n"
                "def require_host(name):assert name=='pikachu'\n"
                "def private_root():assert ROOT.is_dir()\n"
                "def run_identifier(value):assert value=='synthetic-frame'\n")
            test_source="import unittest\nclass Synthetic(unittest.TestCase):\n def test_synthetic(self):self.assertTrue(True)\n"
            request={'run_id':'synthetic-frame','profiles':{},'sources':{
                'etcd_recovery':common_source,'test_valkey_source_aof':test_source}}
            child=subprocess.run([sys.executable,'-I','-B','-c',qualification.BOOT],
                input=aof.json.dumps(request).encode(),capture_output=True)
            self.assertEqual((child.returncode,child.stderr),(0,b''))
            result=aof.json.loads(child.stdout)
            self.assertTrue(result['accepted'])
            self.assertTrue(result['cleanup']['scratch_absent'])
            self.assertEqual(list(Path(temporary).iterdir()),[])

    @unittest.skipUnless(os.geteuid() == 0, 'native Linux root protected six-AOF fixture')
    def test_native_six_source_point_and_protected_tamper_refusal(self):
        with tempfile.TemporaryDirectory(dir=aof.common.ROOT) as temporary, \
                patch.object(aof.common,'ROOT',Path(temporary)),patch.object(aof.common,'require_host'), \
                patch.object(aof.common,'private_root'),patch.object(aof.cohort,'verify',return_value=(None,
                    {'sources':{n:binding(n) for n in aof.cohort.CLAIMS}})):
            nodes={}
            for n in aof.cohort.CLAIMS:
                _header,raw=fixture_stream(n)
                nodes[n]=aof.receive('synthetic-six-aof',core(n),io.BytesIO(raw))
            result=aof.finalize('synthetic-six-aof','a'*64,nodes)
            point,value=aof.verify('synthetic-six-aof',result['manifest_sha256'])
            self.assertEqual(value['nodes'],nodes)
            with self.assertRaises(FileExistsError):aof.finalize('synthetic-six-aof','a'*64,nodes)
            (point/'node-4/appendonly.aof.12.incr.aof').write_bytes(b'synthetic-corruption')
            with self.assertRaises(RuntimeError):aof.verify('synthetic-six-aof',result['manifest_sha256'])

    @unittest.skipUnless(os.geteuid() == 0, 'native Linux root source metadata fixture')
    def test_native_source_metadata_and_link_refusal(self):
        with tempfile.TemporaryDirectory(dir=aof.common.ROOT) as temporary:
            root=Path(temporary)
            path=root/'appendonly.aof.1.incr.aof'
            path.write_bytes(b'')
            os.chown(path,1001,1001)
            for mode in (0o644,0o664):
                path.chmod(mode)
                record,_identity=aof.source_file(path)
                self.assertEqual(record,{'bytes':0,'sha256':hashlib.sha256(b'').hexdigest(),'source_mode':mode})
            link=root/'hardlink';os.link(path,link)
            with self.assertRaises(RuntimeError):aof.source_file(path)
            link.unlink();link.symlink_to(path)
            with self.assertRaises(OSError):aof.source_file(link)
            link.unlink();path.chmod(0o666)
            with self.assertRaises(RuntimeError):aof.source_file(path)
            path.unlink();os.mkfifo(path)
            with self.assertRaises(RuntimeError):aof.source_file(path)

    def test_manifest_refuses_path_sequence_kind_and_extra_segments(self):
        raw = b'file appendonly.aof.12.base.rdb seq 12 type b\nfile appendonly.aof.12.incr.aof seq 12 type i\n'
        self.assertEqual(len(aof.parse_manifest(raw)),3)
        for altered in (raw[:-1],raw.replace(b'file append',b'file ../append',1),raw.replace(b'seq 12',b'seq 13',1),
                raw.replace(b'type b',b'type i',1),raw+raw.splitlines()[1]+b'\n',b'\xff\n'):
            with self.subTest(altered=altered), self.assertRaises(RuntimeError):
                aof.parse_manifest(altered)

    def test_frame_requires_bound_source_and_exact_safe_metadata(self):
        header,_raw=fixture_stream()
        self.assertEqual(aof.validate_header(header),header)
        changes=(lambda v:v['source'].update(claim_uid='foreign'),lambda v:v.update(format='historical'),
            lambda v:v['files'].update({'../escape':v['files'].pop(aof.MANIFEST)}),
            lambda v:v['files'][aof.MANIFEST].update(bytes=4097),
            lambda v:v['files'][aof.MANIFEST].update(source_mode=0o666),
            lambda v:v['files'][aof.MANIFEST].update(bytes=True))
        for change in changes:
            altered=copy.deepcopy(header);change(altered)
            with self.assertRaises(RuntimeError):aof.validate_header(altered)

    def test_protected_roundtrip_empty_incremental_and_no_overwrite(self):
        header,raw=fixture_stream()
        with tempfile.TemporaryDirectory() as temporary, patch.object(aof.common,'ROOT',Path(temporary)), \
                patch.object(aof.common,'require_host'),patch.object(aof.common,'private_root'):
            self.assertEqual(aof.receive('synthetic-roundtrip',core(),io.BytesIO(raw)),header)
            root=aof.point_path('synthetic-roundtrip')/'node-0'
            self.assertEqual((root/'appendonly.aof.12.incr.aof').read_bytes(),b'')
            self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in root.iterdir()))
            with self.assertRaises(FileExistsError):aof.receive('synthetic-roundtrip',core(),io.BytesIO(raw))

    def test_missing_commit_corruption_and_trailing_bytes_never_accepted(self):
        _header,raw=fixture_stream()
        with tempfile.TemporaryDirectory() as temporary,patch.object(aof.common,'ROOT',Path(temporary)), \
                patch.object(aof.common,'require_host'),patch.object(aof.common,'private_root'):
            for n,altered in enumerate((raw[:-1],raw+b'foreign',raw.replace(b'REDIS0012',b'REDIS9999'))):
                run_id='synthetic-bad-'+str(n)
                with self.assertRaises(RuntimeError):aof.receive(run_id,core(),io.BytesIO(altered))
                self.assertFalse((aof.point_path(run_id)/'node-0/source.json').exists())


if __name__ == '__main__':
    unittest.main()
