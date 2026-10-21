"""Credential containment and allowed-account-change regression checks."""

from copy import deepcopy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from contextlib import nullcontext
from types import SimpleNamespace

import kanidm_account_recovery as recovery


class AccountRecoveryTests(unittest.TestCase):
    def test_authenticated_identity_and_logout_on_refusal(self):
        for name in ('admin', 'foreign-account'):
            calls = []
            class Opener:
                def open(self, request, **_kwargs):
                    calls.append(request.full_url)
                    values = [{'state': {'choose': ['password']}},
                              {'state': {'continue': ['password']}},
                              {'state': {'success': 'synthetic-session'}},
                              {'youare': {'attrs': {'name': [name]}}}, None]
                    return nullcontext(SimpleNamespace(status=200, read=lambda _limit: json.dumps(values[len(calls)-1]).encode()))
            with patch.object(recovery.urllib.request, 'build_opener', return_value=Opener()):
                if name == 'admin':
                    self.assertTrue(recovery.verify_https_login('synthetic-password')['session_logout'])
                else:
                    with self.assertRaises(RuntimeError):
                        recovery.verify_https_login('synthetic-password')
            self.assertEqual(calls[-1], 'https://auth.eaglepass.io/v1/logout')

    def test_existing_multifactor_credential_is_not_discarded(self):
        account = {'name': {'N8': ['admin']}, 'primary_credential': {
            'CR': [{'t': 'primary', 'd': {'type_': 'V2GPw'}}]}}
        backup = {'entries': [{'ent': {'V3': {'attrs': account}}}]}
        recovery.require_password_only_admin(backup)
        account['primary_credential']['CR'][0]['d']['type_'] = 'V3PwMfa'
        with self.assertRaises(RuntimeError):
            recovery.require_password_only_admin(backup)

    def test_native_container_arguments_preserve_label_value_pairs(self):
        for operation in ('server', 'cert-generate'):
            args = recovery.server_arguments(Path('/synthetic'), 'fixture', operation)
            labels = [args[i + 1] for i, arg in enumerate(args) if arg == '--label']
            self.assertEqual(labels, [recovery.LABEL + '=fixture', recovery.native.LABEL + '=fixture'])
            self.assertEqual(args[-3:], [recovery.native.IMAGE, '--config-path=/data/offline.toml', operation])
        with self.assertRaises(RuntimeError):
            recovery.server_arguments(Path('/synthetic'), 'fixture', 'other')

    def test_native_success_and_sanitized_refusals(self):
        password = 'synthetic-password-value-103'
        self.assertEqual(recovery.decode_password(json.dumps({'status': 'ok', 'output': password})), password)
        for raw in ('{"status":"error","output":"' + password + '"}',
                    '{"status":"ok","status":"error","output":"' + password + '"}',
                    '{"status":"ok","output":12}', 'private malformed output',
                    '{"status":"ok","output":"short"}'):
            with self.assertRaises(RuntimeError) as error:
                recovery.decode_password(raw)
            self.assertNotIn(password, str(error.exception))
            self.assertNotIn('private malformed output', str(error.exception))

    def item(self):
        return {'id': recovery.ITEM, 'vault': {'id': recovery.VAULT}, 'category': 'LOGIN',
                'version': 3, 'fields': [{'id': 'username', 'purpose': 'USERNAME', 'value': 'admin'},
                {'id': 'password', 'purpose': 'PASSWORD', 'type': 'CONCEALED', 'value': 'old'}]}

    def test_vault_preserves_account_and_all_other_fields(self):
        original = self.item()
        password = 'synthetic-password-value-103'
        updated = recovery.replace_password(original, password)
        self.assertEqual(original['fields'][1]['value'], 'old')
        updated['fields'][1]['password_details'] = {'history': ['old']}
        updated['version'] = 4
        recovery.verify_vault(original, updated, password)
        altered = deepcopy(updated)
        altered['fields'][1]['password_details']['history'] = ['unapproved-history']
        with self.assertRaises(RuntimeError):
            recovery.verify_vault(original, altered, password)
        updated['fields'][0]['value'] = 'other'
        with self.assertRaises(RuntimeError):
            recovery.verify_vault(original, updated, password)

    def test_vault_passkey_or_foreign_identity_refused(self):
        for field, value in [('passkeys', [{}]), ('id', 'other'), ('passkeyMetadata', {})]:
            item = self.item()
            item[field] = value
            with self.assertRaises(RuntimeError):
                recovery.replace_password(item, 'synthetic-password-value-103')

    def test_account_only_password_changes(self):
        def entry(identity, name):
            return {'ent': {'V3': {'attrs': {'uuid': identity, 'name': {'N8': [name]},
                                           'primary_credential': 'old', 'membership': ['keep']}}}}
        before = {'entries': [entry('one', 'admin'), entry('two', 'another')]}
        after = deepcopy(before)
        after['entries'][0]['ent']['V3']['attrs']['primary_credential'] = 'new'
        after['entries'][0]['ent']['V3']['attrs']['account_valid_from'] = {'DT': ['2026-10-21T22:00:00Z']}
        bounds = (1792620000 * 10**9, 1792620001 * 10**9)
        self.assertTrue(recovery.account_changes(before, after, *bounds)['only_admin_native_recovery_fields_changed'])
        for mutate in ('membership', 'foreign', 'removed'):
            bad = deepcopy(after)
            if mutate == 'membership':
                bad['entries'][0]['ent']['V3']['attrs']['membership'] = []
            elif mutate == 'foreign':
                bad['entries'][1]['ent']['V3']['attrs']['primary_credential'] = 'new'
            else:
                bad['entries'].pop()
            with self.assertRaises(RuntimeError):
                recovery.account_changes(before, bad, *bounds)
        for field in ('passkeys', 'account_expire'):
            bad = deepcopy(before)
            bad['entries'][0]['ent']['V3']['attrs'][field] = ['must-preserve']
            with self.assertRaises(RuntimeError):
                recovery.account_changes(bad, after, *bounds)
        with self.assertRaises(RuntimeError):
            recovery.account_changes(before, after, 0, 1)


if __name__ == '__main__':
    unittest.main()
