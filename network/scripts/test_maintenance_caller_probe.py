"""Strict public health-response and endpoint boundary checks."""

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


if __name__ == '__main__':
    unittest.main()
