"""Keep maintained-source catalogs private and reject unbound profiles."""

import json
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

import gitea_cohort_recovery as cohort
import gitea_recovery_transport as transport
import gitea_capture_only_qualification as lease


class MaintainedCohortTests(unittest.TestCase):
    def test_source_profile_requires_exact_payload_and_never_enters_role_recovery(self):
        with self.assertRaises(RuntimeError):
            cohort.Controller(['kubectl'], None, source_image=cohort.maintained.IMAGE)
        with self.assertRaises(RuntimeError):
            cohort.Controller(['kubectl'], None, postgres_payload={})
        with patch.object(cohort.maintained, 'validate_payload') as validate:
            instance = cohort.Controller(['kubectl'], None, source_image=cohort.maintained.IMAGE, postgres_payload={'public': True})
            validate.assert_called_once_with({'public': True})
        with patch.object(instance, 'call') as call, self.assertRaisesRegex(RuntimeError, 'capture-only'):
            instance.recover('synthetic', lambda *_a, **_k: None)
        call.assert_not_called()

    def test_restore_dispatch_binds_existing_credentials_and_exact_profile(self):
        for maintained in (False, True):
            bundle = Mock()
            with patch.object(cohort.maintained, 'validate_payload'):
                instance = cohort.Controller(['kubectl'], bundle,
                    source_image=cohort.maintained.IMAGE if maintained else cohort.postgres.source.cold.control.IMAGE,
                    postgres_payload={'public': True} if maintained else None)
            instance.credentials={'admin':'synthetic-admin','app':'synthetic-app'}
            instance.hba=b'synthetic-hba'
            instance.restore_postgres({'point':'/synthetic','manifest_sha256':'a'*64}, 'synthetic')
            self.assertEqual(bundle.run.call_args.args, ('pikachu','postgres_maintained_restore' if maintained else 'restore'))
            self.assertEqual(bundle.run.call_args.kwargs['credentials'], instance.credentials)
            self.assertEqual(bundle.run.call_args.kwargs.get('payload'), {'public': True} if maintained else None)

    def test_only_internal_restore_frame_returns_catalog(self):
        bundle=object.__new__(transport.Bundle)
        bundle.profiles={}
        bundle.sources={'etcd_recovery':'','gitea_postgres_cold_point':'','gitea_postgres_guarded_source':'','gitea_postgres_fresh_restore':'',
            'gitea_postgres_maintained_qualification': "def run(*args,return_catalog=False):\n return ({'accepted':True},{'private-synthetic-verifier':True}) if return_catalog else {'accepted':True}\n"}
        args={'point':'/synthetic','checksum':'a'*64,'credentials':{},'hba':'','run_id':'synthetic','payload':{}}
        for operation in ('postgres_maintained_restore','postgres_image_qualify'):
            child=subprocess.run([sys.executable,'-I','-B','-c',transport.BOOT],input=bundle.request(operation,args),capture_output=True)
            self.assertEqual((child.returncode,child.stderr),(0,b''))
            result=json.loads(child.stdout)
            if operation=='postgres_image_qualify':
                self.assertEqual(result,{'accepted':True})
                self.assertNotIn(b'private-synthetic-verifier',child.stdout)
            else:self.assertEqual(result,{'summary':{'accepted':True},'catalog':{'private-synthetic-verifier':True}})

    def test_unknown_native_lease_mode_refused_before_runtime(self):
        with patch.object(lease.common,'require_no_logging') as logging, patch.object(lease.recovery,'execute') as execute:
            with self.assertRaisesRegex(RuntimeError,'unreviewed'):
                lease.lease('synthetic','foreign')
        logging.assert_not_called();execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
