"""Credential containment and allowed-account-change regression checks."""

from copy import deepcopy
import json
import unittest

import kanidm_account_recovery as recovery


class AccountRecoveryTests(unittest.TestCase):
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
        updated['version'] = 4
        recovery.verify_vault(original, updated, password)
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
            return {'ent': {'V3': {'attrs': {'uuid': identity, 'name': {'IN': [name]},
                                           'primary_credential': 'old', 'membership': ['keep']}}}}
        before = {'entries': [entry('one', 'admin'), entry('two', 'another')]}
        after = deepcopy(before)
        after['entries'][0]['ent']['V3']['attrs']['primary_credential'] = 'new'
        self.assertTrue(recovery.account_changes(before, after)['only_admin_primary_credential_changed'])
        for mutate in ('membership', 'foreign', 'removed'):
            bad = deepcopy(after)
            if mutate == 'membership':
                bad['entries'][0]['ent']['V3']['attrs']['membership'] = []
            elif mutate == 'foreign':
                bad['entries'][1]['ent']['V3']['attrs']['primary_credential'] = 'new'
            else:
                bad['entries'].pop()
            with self.assertRaises(RuntimeError):
                recovery.account_changes(before, bad)


if __name__ == '__main__':
    unittest.main()
