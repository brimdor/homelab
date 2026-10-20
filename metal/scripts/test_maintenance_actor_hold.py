"""Persistent owner/guard safety tests; native systemd qualification is separate."""

import json
from contextlib import nullcontext
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import maintenance_actor_hold as actors


TOKEN = 'homelab-maintenance-103-11111111-1111-4111-8111-111111111111'
IDENTITY = {'machine': 'synthetic-machine', 'root_uuid': 'synthetic-root'}


class Systemd:
    def __init__(self):
        self.calls = []
        self.active = False

    def reload(self):
        self.calls.append('reload')

    def idle(self, marker):
        self.calls.append('idle')
        if self.active:
            raise RuntimeError('package actor active')
        assert marker.is_file()


class ActorHold(unittest.TestCase):
    def fixture(self, root):
        units = root / 'units'
        units.mkdir()
        native = Systemd()
        owner = actors.Hold(native, lambda: dict(IDENTITY), lambda t: t == TOKEN,
                            root / 'state', units)
        return owner, native

    def test_persistent_independent_resume_and_failed_release_keep_all_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner, native = self.fixture(root)
            result = owner.acquire(TOKEN, IDENTITY, 'a' * 40)
            saved = owner.marker.read_bytes()
            fresh = actors.Hold(native, lambda: dict(IDENTITY), lambda t: t == TOKEN,
                                root / 'state', root / 'units')
            self.assertEqual(fresh.resume(TOKEN), result)
            with self.assertRaisesRegex(RuntimeError, 'release gates'):
                fresh.release(TOKEN, lambda _v: False)
            self.assertEqual(owner.marker.read_bytes(), saved)
            guards = {s: (root / 'units' / (s + '.d') / actors.GUARD).read_bytes() for s in actors.SERVICES}
            fresh.release(TOKEN, lambda _v: True)
            self.assertFalse(owner.marker.exists())
            self.assertEqual(guards, {s: (root / 'units' / (s + '.d') / actors.GUARD).read_bytes() for s in actors.SERVICES})
            self.assertTrue(set(native.calls) <= {'reload', 'idle'})

    def test_partial_hold_resumes_without_overwriting_foreign_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner, _native = self.fixture(root)
            original = actors.exclusive_file

            def fail(path, data, mode):
                if path.parent.name == actors.SERVICES[1] + '.d':
                    raise RuntimeError('injected controller failure')
                return original(path, data, mode)

            with patch.object(actors, 'exclusive_file', side_effect=fail), self.assertRaisesRegex(RuntimeError, 'injected'):
                owner.acquire(TOKEN, IDENTITY, 'a' * 40)
            self.assertTrue(owner.marker.exists())
            owner.resume(TOKEN)
            owner.guards(install=False)
            guard = root / 'units' / (actors.SERVICES[0] + '.d') / actors.GUARD
            guard.write_text('foreign content')
            with self.assertRaisesRegex(RuntimeError, 'foreign'):
                owner.resume(TOKEN)
            self.assertEqual(guard.read_text(), 'foreign content')
            self.assertTrue(owner.marker.exists())

    def test_active_actor_is_never_stopped_and_ownership_is_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, native = self.fixture(Path(temporary))
            native.active = True
            with self.assertRaisesRegex(RuntimeError, 'active'):
                owner.acquire(TOKEN, IDENTITY, 'a' * 40)
            self.assertTrue(owner.marker.exists())
            owner.guards(install=False)
            self.assertEqual(native.calls, ['reload', 'idle'])
            native.active = False
            owner.resume(TOKEN)

    def test_wrong_host_foreign_owner_and_changed_owner_during_release_refuse(self):
        with tempfile.TemporaryDirectory() as temporary:
            owner, _native = self.fixture(Path(temporary))
            with self.assertRaisesRegex(RuntimeError, 'host identity'):
                owner.acquire(TOKEN, {**IDENTITY, 'machine': 'changed'}, 'a' * 40)
            self.assertFalse(owner.marker.exists())
            owner.acquire(TOKEN, IDENTITY, 'a' * 40)
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                owner.resume(TOKEN.replace('11111111', '22222222'))
            with self.assertRaises(FileExistsError):
                owner.acquire(TOKEN, IDENTITY, 'a' * 40)

            def changed(_value):
                value = json.loads(owner.marker.read_bytes())
                value['revision'] = 'b' * 40
                owner.marker.write_text(json.dumps(value))
                return True

            with self.assertRaisesRegex(RuntimeError, 'changed during'):
                owner.release(TOKEN, changed)
            self.assertTrue(owner.marker.exists())

    def test_symlink_and_shared_permissions_refuse_before_owned_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            units = root / 'units'
            units.mkdir()
            state = root / 'state'
            state.mkdir(mode=0o755)
            with self.assertRaisesRegex(RuntimeError, 'private'):
                actors.Hold(Systemd(), lambda: IDENTITY, lambda _t: True, state, units)
            state.chmod(0o700)
            (state / 'owner.json').symlink_to(root / 'missing')
            owner = actors.Hold(Systemd(), lambda: IDENTITY, lambda _t: True, state, units)
            with self.assertRaises(RuntimeError):
                owner.resume(TOKEN)
            self.assertTrue((state / 'owner.json').is_symlink())

    def test_native_query_contract_accepts_empty_job_and_requires_effective_negated_condition(self):
        marker = Path('/synthetic/owner.json')
        native = actors.Systemd()
        properties = b'MainPID=0\nControlPID=0\nLoadState=loaded\nActiveState=inactive\nJob=\n'
        condition = [['ConditionPathExists', False, True, str(marker), 0]]

        def call(*args):
            if args[0] == 'systemctl':
                return properties
            if 'GetUnit' in args:
                return b'{"type":"o","data":["/org/freedesktop/systemd1/unit/synthetic"]}'
            return json.dumps({'type': 'a(sbbsi)', 'data': condition}).encode()

        with patch.object(native, 'call', side_effect=call), \
                patch.object(native, 'reference', side_effect=lambda _s: nullcontext()), \
                patch.object(Path, 'iterdir', return_value=iter(())):
            native.idle(marker)
            condition[0][2] = False
            with self.assertRaisesRegex(RuntimeError, 'condition absent'):
                native.idle(marker)
            condition[0][2] = True
            properties = properties.replace(b'Job=\n', b'Job=73\n')
            with self.assertRaisesRegex(RuntimeError, 'pending job'):
                native.idle(marker)

    def test_private_native_reference_closes_on_success_query_error_and_refusal(self):
        native = actors.Systemd()
        for outcome in ('success', 'query-error', 'refused'):
            library = MagicMock()

            def opened(pointer):
                pointer._obj.value = 123
                return 0

            def referenced(*args):
                args[6]._obj.value = 456
                return -5 if outcome == 'refused' else 0

            library.sd_bus_open_system.side_effect = opened
            library.sd_bus_call_method.side_effect = referenced
            with patch.object(actors.ctypes, 'CDLL', return_value=library):
                if outcome == 'success':
                    with native.reference(actors.SERVICES[0]):
                        library.sd_bus_flush_close_unref.assert_not_called()
                else:
                    with self.assertRaisesRegex(RuntimeError, 'reference failed|query error'):
                        with native.reference(actors.SERVICES[0]):
                            raise RuntimeError('query error')
            library.sd_bus_flush_close_unref.assert_called_once()
            library.sd_bus_message_unref.assert_called_once()
            self.assertEqual(library.sd_bus_call_method.call_args.args[4], b'RefUnit')


if __name__ == '__main__':
    unittest.main()
