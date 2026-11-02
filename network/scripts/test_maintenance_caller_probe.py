"""Health-response, public/private scope and endpoint boundary checks."""

import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location('caller', Path(__file__).with_name('maintenance-caller-probe.py'))
caller = importlib.util.module_from_spec(spec)
spec.loader.exec_module(caller)


class CallerTests(unittest.TestCase):
    def test_endpoint_contract_refuses_foreign_issuer_and_partial_health(self):
        caller.require_body('gitea', {'version': 'fixture'})
        caller.require_body('grafana', {'database': 'ok'})
        dex = {'issuer': 'https://dex.eaglepass.io', 'authorization_endpoint': 'https://dex.eaglepass.io/auth',
               'token_endpoint': 'https://dex.eaglepass.io/token', 'jwks_uri': 'https://dex.eaglepass.io/keys'}
        caller.require_body('dex', dex)
        for name, body in [('gitea', {'version': ''}), ('grafana', {'database': 'failed'}),
                           ('dex', dex | {'token_endpoint': 'https://foreign.example/token'}), ('dex', [])]:
            with self.assertRaises(ValueError):
                caller.require_body(name, body)

    def test_foreign_target_refused_before_connect(self):
        with self.assertRaises(ValueError):
            caller.probe('gitea', '10.0.40.3', '/')

    def test_outside_origin_preserves_private_access_policy(self):
        self.assertEqual(caller.targets('outside-lan'), caller.PUBLIC_TARGETS)
        self.assertEqual(caller.targets('collector'), caller.TARGETS)
        self.assertEqual(caller.targets('tailnet'), caller.TARGETS)
        self.assertTrue(set(caller.PUBLIC_TARGETS).isdisjoint(caller.TARGETS))
        with self.assertRaises(ValueError):
            caller.targets('foreign')

    def test_public_health_contracts_refuse_partial_or_wrong_typed_success(self):
        for name in ('builder-canary', 'builder-production'):
            caller.require_body(name, {'ok': True})
            for value in ({}, {'ok': 1}, {'ok': 'true'}, {'ok': False}):
                with self.assertRaises(ValueError):
                    caller.require_body(name, value)

    def test_public_names_cannot_be_recombined_with_foreign_paths(self):
        for target in (('builder-canary', 'builder-canary.eaglepass.io', '/'),
                       ('builder-canary', 'builder.eaglepass.io', '/healthz'),
                       ('gitea', 'builder-canary.eaglepass.io', '/api/v1/version')):
            with self.assertRaises(ValueError):
                caller.probe(*target)


if __name__ == '__main__':
    unittest.main()
