"""Offline safety tests. No credentials, router calls or real recovery files."""

import copy
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import ssl
import stat
import tempfile
import unittest
from unittest.mock import patch
import uuid


SPEC = importlib.util.spec_from_file_location("private_dns", Path(__file__).with_name("reconcile-private-dns.py"))
dns = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dns)
ROWS = json.loads(dns.DESIRED.read_text())["hosts"]
ORIGINAL_NAMES = {"git", "registry", "auth"}
DEFAULTS = {k: "" for k in dns.HOST_FIELDS}
DEFAULTS.update(local="0", ignore="0")


def state():
    return {"version": dns.VERSION, "defaults": copy.deepcopy(DEFAULTS), "source_hash": "",
            "dnsmasq": {"enable": "1", "dns_port": "53", "hosts": {}, "dhcp": {"enable_ra": "0"},
                        "dhcp_ranges": {}, "no_resolv": "0", "domainoverrides": {}},
            "unbound": {"unbound": {"advanced": {"privatedomain": "registry.eaglepass.io"}}},
            "nameservers": ["1.1.1.1"], "rebind_protection": True, "dhcp_sockets": []}


class FakeRouter:
    def __init__(self):
        self.state = state()
        self.calls = []
        self.failure = None

    def post(self, endpoint, payload):
        # Serialize and decode the real API wire payload, not a Python-only fixture.
        payload = json.loads(json.dumps(payload))
        self.calls.append((endpoint, payload))
        if self.failure:
            return self.failure
        if endpoint == dns.ADD:
            key = str(uuid.uuid4())
            self.state["dnsmasq"]["hosts"][key] = {**DEFAULTS, **payload["host"]}
            return {"result": "saved", "uuid": key}
        if endpoint.startswith(dns.DELETE):
            del self.state["dnsmasq"]["hosts"][endpoint[len(dns.DELETE):]]
            return {"result": "deleted"}
        if endpoint == dns.RESTART:
            return {"response": "OK"}
        raise AssertionError("Unexpected write endpoint")


class ScopeTests(unittest.TestCase):
    def test_desired_and_wire_schema(self):
        self.assertEqual(dns.validate_desired(json.loads(dns.DESIRED.read_text())), ROWS)
        self.assertEqual(json.loads(json.dumps(dns.add_payload(ROWS[0]))), {
            "host": {"host": "git", "domain": "eaglepass.io", "ip": "10.0.20.226", "local": "0"}})

    def test_reject_scope_expansion(self):
        for field, value in [("host", "*"), ("domain", "example.com"), ("ip", "1.1.1.1"),
                             ("local", "1"), ("local", 0), ("host", "git\ninvalid"),
                             ("host", "unreviewed"), ("host", "omni-tools-canary")]:
            with self.subTest(field=field, value=value):
                candidate = copy.deepcopy(ROWS)
                candidate[0][field] = value
                with self.assertRaises(dns.Refusal):
                    dns.validate_desired({"firmware_version": dns.VERSION, "hosts": candidate})

    def test_fixed_reviewed_names_and_exact_count(self):
        approved = {"git", "registry", "auth", "argocd", "dex", "grafana", "radarr",
                    "sabnzbd", "searxng", "sonarr", "ci"}
        self.assertEqual(dns.NAMES, approved)
        for rows in (ROWS[:-1], ROWS + [ROWS[0]], ROWS[:-1] + [ROWS[0]],
                     ROWS + [{**ROWS[0], "host": "unreviewed"}]):
            with self.subTest(count=len(rows)), self.assertRaises(dns.Refusal):
                dns.validate_desired({"firmware_version": dns.VERSION, "hosts": rows})

    def test_extra_fields_and_wrong_version(self):
        candidate = copy.deepcopy(ROWS)
        candidate[0]["hwaddr"] = "00:11:22:33:44:55"
        for data in [{"firmware_version": dns.VERSION, "hosts": candidate},
                     {"firmware_version": "25.7.9", "hosts": ROWS}]:
            with self.assertRaises(dns.Refusal):
                dns.validate_desired(data)

    def test_preserve_unrelated_user_rows_and_idempotency(self):
        before = state()
        before["dnsmasq"]["hosts"][str(uuid.uuid4())] = {**DEFAULTS, "host": "printer", "domain": "home", "ip": "10.0.0.8"}
        saved = copy.deepcopy(before)
        self.assertEqual(dns.plan(before, ROWS), ROWS)
        self.assertEqual(before, saved)
        for row in ROWS:
            before["dnsmasq"]["hosts"][str(uuid.uuid4())] = {**DEFAULTS, **row}
        self.assertEqual(dns.plan(before, ROWS), [])

    def test_existing_conflict_alias_wildcard_and_short_name(self):
        for changes in [{"host": "git", "domain": "eaglepass.io", "ip": "10.0.20.227"},
                        {"host": "git", "domain": "another.zone"},
                        {"host": "*", "domain": "eaglepass.io"},
                        {"host": "other", "cnames": "git.eaglepass.io."},
                        {"host": "other", "aliases": "printer,git"},
                        {"host": "other", "cnames": "AUTH."},
                        {**ROWS[0], "local": "1"}, {**ROWS[0], "hwaddr": "00:11:22:33:44:55"}]:
            candidate = state()
            candidate["dnsmasq"]["hosts"][str(uuid.uuid4())] = {**DEFAULTS, **changes}
            with self.subTest(changes=changes), self.assertRaises(dns.Refusal):
                dns.plan(candidate, ROWS)

    def test_duplicate_existing_target(self):
        candidate = state()
        candidate["dnsmasq"]["hosts"] = {str(uuid.uuid4()): {**DEFAULTS, **ROWS[0]} for _ in range(2)}
        with self.assertRaises(dns.Refusal):
            dns.plan(candidate, ROWS)

    def test_option_normalization(self):
        self.assertEqual(dns.normalize({"a": {"selected": 0}, "b": {"selected": 1}}), "b")
        self.assertEqual(dns.normalize([{"value": "off", "selected": 0}, {"value": "on", "selected": 1}]), "1")


class MutationTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeRouter()
        self.events = []
        self.snapshot = patch.object(dns, "snapshot", side_effect=lambda api: copy.deepcopy(api.state))
        self.snapshot.start()
        self.addCleanup(self.snapshot.stop)

    def test_add_reviewed_hosts_then_restart_preserves_every_other_field(self):
        key = str(uuid.uuid4())
        self.api.state["dnsmasq"]["hosts"][key] = {**DEFAULTS, "host": "printer", "ip": "10.0.0.8"}
        initial = copy.deepcopy(self.api.state)
        final = dns.reconcile(self.api, initial, ROWS, self.events.append)
        self.assertEqual([p for p, _ in self.api.calls], [dns.ADD] * len(ROWS) + ["/api/dnsmasq/service/restart"])
        self.assertEqual(self.api.calls[-1][1], {})
        self.assertEqual(final["dnsmasq"]["hosts"][key], initial["dnsmasq"]["hosts"][key])
        final["dnsmasq"]["hosts"] = initial["dnsmasq"]["hosts"]
        self.assertEqual(final, initial)

    def test_stale_guard_refuses_before_first_write(self):
        expected = copy.deepcopy(self.api.state)
        self.api.state["dnsmasq"]["no_resolv"] = "1"
        with self.assertRaises(dns.Refusal):
            dns.reconcile(self.api, expected, ROWS, self.events.append)
        self.assertEqual(self.api.calls, [])

    def test_failed_add_never_retried(self):
        self.api.failure = {"result": "failed", "validations": {"host.ip": "not printed"}}
        with self.assertRaises(dns.Refusal):
            dns.reconcile(self.api, copy.deepcopy(self.api.state), ROWS, self.events.append)
        self.assertEqual(len(self.api.calls), 1)

    def test_uncertain_write_never_retried_or_deleted(self):
        original = self.api.post
        def lose_response(path, payload):
            original(path, payload)
            raise ConnectionError("synthetic sensitive exception")
        self.api.post = lose_response
        with self.assertRaises(ConnectionError):
            dns.reconcile(self.api, copy.deepcopy(self.api.state), ROWS, self.events.append)
        self.assertEqual(len(self.api.calls), 1)
        self.assertEqual(len(self.api.state["dnsmasq"]["hosts"]), 1)

    def test_readback_drift_stops_followup_writes(self):
        original = self.api.post
        def drift(path, payload):
            response = original(path, payload)
            self.api.state["dnsmasq"]["no_resolv"] = "1"
            return response
        self.api.post = drift
        with self.assertRaises(dns.Refusal):
            dns.reconcile(self.api, copy.deepcopy(self.api.state), ROWS, self.events.append)
        self.assertEqual(len(self.api.calls), 1)
        self.assertEqual(self.events[-1]["event"], "add_acknowledged")

    def test_exact_uuid_rollback_and_changed_uuid_refusal(self):
        backup = b'<opnsense><dnsmasq version="1.0.8"/></opnsense>'
        self.events.append({"event": "backup", "backup_sha256": hashlib.sha256(backup).hexdigest()})
        final = dns.reconcile(self.api, copy.deepcopy(self.api.state), ROWS, self.events.append)
        targets = dns.rollback_plan(self.events, final, backup)
        self.assertEqual(len(targets), len(ROWS))
        altered = copy.deepcopy(final)
        altered["dnsmasq"]["hosts"][targets[0]["uuid"]]["ip"] = "10.0.20.227"
        with self.assertRaises(dns.Refusal):
            dns.rollback_plan(self.events, altered, backup)
        dns.rollback(self.api, final, targets, self.events.append)
        deletes = [p[len(dns.DELETE):] for p, _ in self.api.calls if p.startswith(dns.DELETE)]
        self.assertEqual(deletes, [t["uuid"] for t in reversed(targets)])
        self.assertEqual([p for p, _ in self.api.calls], [dns.ADD] * len(ROWS) + [dns.RESTART]
                         + [dns.DELETE + t["uuid"] for t in reversed(targets)] + [dns.RESTART])
        self.assertEqual(self.api.state["dnsmasq"]["hosts"], {})

    def test_failed_or_uncertain_restart_never_retried_for_apply_or_rollback(self):
        for rollback in (False, True):
            for response in ({"status": "ok"}, {"response": ""}, {"response": "Error (1)"}, None):
                with self.subTest(rollback=rollback, response=response):
                    api = FakeRouter()
                    events = []
                    initial = copy.deepcopy(api.state)
                    if rollback:
                        initial = dns.reconcile(api, initial, ROWS, events.append)
                        targets = [event for event in events if event["event"] == "created"]
                        api.calls.clear()
                    original = api.post
                    def fail_restart(path, payload):
                        if path == dns.RESTART:
                            api.calls.append((path, payload))
                            if response is None:
                                raise ConnectionError("synthetic lost restart response")
                            return response
                        return original(path, payload)
                    api.post = fail_restart
                    with self.assertRaises((dns.Refusal, ConnectionError)):
                        if rollback:
                            dns.rollback(api, initial, targets, events.append)
                        else:
                            dns.reconcile(api, initial, ROWS, events.append)
                    self.assertEqual([p for p, _ in api.calls].count(dns.RESTART), 1)
                    self.assertEqual(len(api.calls), len(ROWS) + 1)
                    self.assertEqual(events[-1]["event"], "before_restart")

    def test_partial_receipt_cannot_auto_rollback(self):
        with self.assertRaises(dns.Refusal):
            dns.rollback_plan([{"event": "backup"}, {"event": "before_add"}], self.api.state, b"")

    def test_rollback_preserves_preexisting_target_and_unrelated_row(self):
        owned_before = {str(uuid.uuid4()): {**DEFAULTS, **ROWS[0]},
                        str(uuid.uuid4()): {**DEFAULTS, "host": "printer", "ip": "10.0.0.8"}}
        self.api.state["dnsmasq"]["hosts"] = copy.deepcopy(owned_before)
        backup = ('<opnsense><dnsmasq>' + ''.join(f'<hosts uuid="{key}"/>' for key in owned_before)
                  + '</dnsmasq></opnsense>').encode()
        self.events.append({"event": "backup", "backup_sha256": hashlib.sha256(backup).hexdigest()})
        final = dns.reconcile(self.api, copy.deepcopy(self.api.state), ROWS, self.events.append)
        targets = dns.rollback_plan(self.events, final, backup)
        self.assertEqual(len(targets), len(ROWS) - 1)
        self.assertFalse(set(owned_before) & {e["uuid"] for e in targets})
        with self.assertRaises(dns.Refusal):
            dns.rollback_plan(self.events, final, backup + b' ')
        dns.rollback(self.api, final, targets, self.events.append)
        self.assertEqual(self.api.state["dnsmasq"]["hosts"], owned_before)

    def test_expand_preserves_original_three_and_rolls_back_only_new_rows(self):
        original_rows = {str(uuid.uuid4()): {**DEFAULTS, **row} for row in ROWS if row["host"] in ORIGINAL_NAMES}
        self.assertEqual(len(original_rows), len(ORIGINAL_NAMES))
        self.api.state["dnsmasq"]["hosts"] = copy.deepcopy(original_rows)
        initial = copy.deepcopy(self.api.state)
        missing = [row for row in ROWS if row["host"] not in ORIGINAL_NAMES]
        self.assertEqual(dns.plan(initial, ROWS), missing)
        backup = ('<opnsense><dnsmasq>' + ''.join(f'<hosts uuid="{key}"/>' for key in original_rows)
                  + '</dnsmasq></opnsense>').encode()
        self.events.append({"event": "backup", "backup_sha256": hashlib.sha256(backup).hexdigest()})
        final = dns.reconcile(self.api, initial, ROWS, self.events.append)
        self.assertEqual(self.api.calls, [(dns.ADD, {"host": row}) for row in missing] + [(dns.RESTART, {})])
        self.assertEqual({key: final["dnsmasq"]["hosts"][key] for key in original_rows}, original_rows)
        targets = dns.rollback_plan(self.events, final, backup)
        self.assertEqual(len(targets), len(dns.NAMES) - len(ORIGINAL_NAMES))
        self.assertFalse(set(original_rows) & {event["uuid"] for event in targets})
        self.api.calls.clear()
        dns.rollback(self.api, final, targets, self.events.append)
        self.assertEqual(self.api.calls, [(dns.DELETE + event["uuid"], {}) for event in reversed(targets)] + [(dns.RESTART, {})])
        self.assertEqual(self.api.state, initial)

    def test_old_three_row_receipt_remains_valid_but_rejects_later_state_drift(self):
        backup = b'<opnsense><dnsmasq version="1.0.8"/></opnsense>'
        self.events.append({"event": "backup", "backup_sha256": hashlib.sha256(backup).hexdigest()})
        original_rows = [row for row in ROWS if row["host"] in ORIGINAL_NAMES]
        original_final = dns.reconcile(self.api, copy.deepcopy(self.api.state), original_rows, self.events.append)
        old_events = copy.deepcopy(self.events)
        targets = dns.rollback_plan(old_events, original_final, backup)
        self.assertEqual(len(targets), len(ORIGINAL_NAMES))
        expanded = dns.reconcile(self.api, copy.deepcopy(original_final), ROWS, self.events.append)
        with self.assertRaises(dns.Refusal):
            dns.rollback_plan(old_events, expanded, backup)
        self.assertEqual(dns.rollback_plan(old_events, original_final, backup), targets)


class BoundaryTests(unittest.TestCase):
    def snapshot_api(self):
        from unittest.mock import Mock
        api = Mock()
        values = {
            "/api/core/firmware/info": {"product_id": "opnsense", "product_version": dns.VERSION,
                                         "product": {"product_hash": dns.CORE_HASH[:9]}},
            "/api/dnsmasq/settings/get_host": {"host": DEFAULTS},
            dns.SETTINGS: {"dnsmasq": state()["dnsmasq"]},
            "/api/dnsmasq/service/status": {"status": "running"},
            "/api/unbound/settings/get": {},
            "/api/unbound/settings/get_nameservers": ["1.1.1.1"],
            dns.SOCKETS: {"statistics": {"Active Internet connections": {
                "dns": {"protocol": "udp4", "command": "dnsmasq", "pid": "42", "local": {"address": "*", "port": "53"}}}}},
        }
        api.get.side_effect = lambda path: copy.deepcopy(values[path])
        api.request.return_value = b'<input name="nodnsrebindcheck" type="checkbox">'
        return api, values

    def test_running_version_model_and_global_rebind_guards(self):
        api, values = self.snapshot_api()
        self.assertEqual(dns.snapshot(api)["version"], dns.VERSION)
        values["/api/core/firmware/info"]["product_version"] = "25.7.10"
        with self.assertRaises(dns.Refusal):
            dns.snapshot(api)
        values["/api/core/firmware/info"]["product_version"] = dns.VERSION
        values["/api/dnsmasq/settings/get_host"]["host"] = {**DEFAULTS, "unknown": ""}
        with self.assertRaises(dns.Refusal):
            dns.snapshot(api)
        values["/api/dnsmasq/settings/get_host"]["host"] = DEFAULTS
        api.request.return_value = b'<input name="nodnsrebindcheck" type="checkbox" checked>'
        with self.assertRaises(dns.Refusal):
            dns.snapshot(api)

    def test_dhcp_or_ra_blocks_restart_before_writes(self):
        for field in ("dhcp_ranges", "enable_ra", "dhcp_socket"):
            api, values = self.snapshot_api()
            if field == "dhcp_ranges":
                values[dns.SETTINGS]["dnsmasq"]["dhcp_ranges"] = {"fixture": {"start": "10.0.0.10"}}
            elif field == "enable_ra":
                values[dns.SETTINGS]["dnsmasq"]["dhcp"]["enable_ra"] = "1"
            else:
                values[dns.SOCKETS]["statistics"]["Active Internet connections"]["dhcp"] = {
                    "protocol": "udp4", "command": "dnsmasq", "local": {"address": "*", "port": "67"}}
            with self.subTest(field=field), self.assertRaises(dns.Refusal):
                dns.snapshot(api)
            api.post.assert_not_called()

    def test_cross_origin_and_insecure_urls(self):
        for url in ["http://opnsense.localdomain/", "https://evil.example/", "//evil.example/", "https://user@opnsense.localdomain/"]:
            with self.subTest(url=url), self.assertRaises(dns.Refusal):
                dns.same_origin(url)
        self.assertEqual(dns.same_origin("/ui/core/dashboard").hostname, dns.TLS_NAME)

    def test_missing_csrf_refused(self):
        with self.assertRaises(dns.Refusal):
            dns.csrf_fields({"inputs": {"usernamefld": {"type": "text"}}})

    def test_configuration_post_requires_apply_before_network(self):
        api = object.__new__(dns.Router)
        api.denied, api.apply, api.login_used = False, False, True
        with patch.object(dns.socket, "create_connection") as connect:
            with self.assertRaises(dns.Refusal):
                api.request("POST", dns.ADD, dns.add_payload(ROWS[0]))
            connect.assert_not_called()

    def test_service_allowlist_rejects_reconfigure_firewall_and_other_actions(self):
        api = object.__new__(dns.Router)
        api.denied, api.apply, api.login_used = False, True, True
        for path in ("/api/dnsmasq/service/reconfigure", "/api/firewall/filter/apply",
                     "/api/firewall/alias/reconfigure", "/api/kea/service/restart",
                     "/api/dnsmasq/service/start", "/api/dnsmasq/service/stop"):
            with self.subTest(path=path), patch.object(dns.socket, "create_connection") as connect:
                with self.assertRaises(dns.Refusal):
                    api.request("POST", path, {})
                connect.assert_not_called()
        with patch.object(dns.socket, "create_connection") as connect:
            with self.assertRaises(dns.Refusal):
                api.request("POST", dns.RESTART, {"firewall": "0"})
            connect.assert_not_called()

    def test_restart_transport_sends_only_fixed_endpoint_and_empty_json(self):
        api = object.__new__(dns.Router)
        api.denied, api.apply, api.login_used = False, True, True
        api.csrf = None
        api.jar = dns.http.cookiejar.CookieJar()
        api.certificate = b"fixture-certificate"
        with patch.object(dns.ssl, "SSLContext") as context, patch.object(dns.socket, "create_connection"), \
                patch.object(dns.http.client, "HTTPSConnection") as connection:
            api.context = context.return_value
            api.context.wrap_socket.return_value.getpeercert.return_value = api.certificate
            response = connection.return_value.getresponse.return_value
            response.status = 200
            response.getheader.return_value = None
            response.read.return_value = b'{"response":"OK"}'
            with patch.object(api.jar, "extract_cookies"):
                self.assertEqual(api.post(dns.RESTART, {}), {"response": "OK"})
            request = connection.return_value.request
            request.assert_called_once()
            self.assertEqual(request.call_args.args, ("POST", "/api/dnsmasq/service/restart"))
            self.assertEqual(request.call_args.kwargs["body"], b"{}")

    def test_auth_rejection_blocks_followup(self):
        api = object.__new__(dns.Router)
        api.denied = True
        with patch.object(dns.socket, "create_connection") as connect:
            with self.assertRaises(dns.Refusal):
                api.request("GET", dns.SETTINGS)
            connect.assert_not_called()

    def test_tls_error_prevents_http_credentials(self):
        api = object.__new__(dns.Router)
        api.denied, api.apply, api.login_used = False, False, False
        api.csrf = None
        api.jar = dns.http.cookiejar.CookieJar()
        with patch.object(dns.ssl, "SSLContext") as context, patch.object(dns.socket, "create_connection"), \
                patch.object(dns.http.client, "HTTPSConnection") as connection:
            api.context = context.return_value
            api.context.wrap_socket.side_effect = ssl.SSLCertVerificationError("fixture certificate rejected")
            with self.assertRaises(ssl.SSLCertVerificationError):
                api.request("POST", "/", {"usernamefld": "synthetic", "passwordfld": "synthetic"}, form=True)
            connection.return_value.request.assert_not_called()

    def test_backup_model_mismatch_refused(self):
        with self.assertRaises(dns.Refusal):
            dns.validate_backup(b"<opnsense><system><hostname>another</hostname></system></opnsense>", state(), "bad")

    def test_backup_current_fields_model_and_certificate(self):
        crt = base64.b64encode(b"synthetic public certificate").decode()
        document = (f'<opnsense><system><hostname>OPNsense</hostname><domain>localdomain</domain>'
                    f'<webgui><ssl-certref>fixture</ssl-certref></webgui></system>'
                    f'<cert><refid>fixture</refid><crt>{crt}</crt></cert>'
                    '<dnsmasq version="1.0.8"><enable>1</enable><no_resolv>0</no_resolv>'
                    '<dhcp><enable_ra>0</enable_ra></dhcp></dnsmasq></opnsense>').encode()
        digest = hashlib.sha256(b"fixture-der").hexdigest()
        with patch.object(dns.ssl, "PEM_cert_to_DER_cert", return_value=b"fixture-der"):
            self.assertEqual(dns.validate_backup(document, state(), digest).tag, "opnsense")
            for malformed in [document.replace(b'1.0.8', b'1.0.9'),
                              document.replace(b'<no_resolv>0', b'<no_resolv>1'),
                              document.replace(b'<webgui>', b'<webgui><nodnsrebindcheck/>')]:
                with self.assertRaises(dns.Refusal):
                    dns.validate_backup(malformed, state(), digest)
            with self.assertRaises(dns.Refusal):
                dns.validate_backup(document, state(), "wrong-cert-digest")

    def test_dirty_or_unpushed_source_gate(self):
        values = {
            ("rev-parse", "--show-toplevel"): str(dns.ROOT),
            ("remote", "get-url", "origin"): dns.ORIGIN,
            ("branch", "--show-current"): "master",
            ("rev-parse", "HEAD"): "a" * 40,
            ("ls-remote", "--exit-code", "origin", "refs/heads/master"): "b" * 40 + "\trefs/heads/master",
        }
        def git(args, **kwargs):
            if args[1] in ("status", "ls-files"):
                return b""
            return values[tuple(args[1:])].encode()
        with patch.object(dns, "run", side_effect=git), self.assertRaises(dns.Refusal):
            dns.git_gate()
        def dirty(args, **kwargs):
            if args[1] == "status":
                return b" M network/scripts/reconcile-private-dns.py"
            return git(args)
        with patch.object(dns, "run", side_effect=dirty), self.assertRaises(dns.Refusal):
            dns.git_gate()


class IngressSuccessorTests(unittest.TestCase):
    def fixture(self):
        selector = {"app.kubernetes.io/name": "traefik",
                    "app.kubernetes.io/instance": "ingress-nginx-ingress-nginx"}
        config = """tcp:
  routers:
    gitea-ssh:
      entryPoints:
      - ssh
      rule: HostSNI(`*`)
      service: gitea-ssh
  services:
    gitea-ssh:
      loadBalancer:
        servers:
        - address: gitea-ssh.gitea.svc.cluster.local:2222"""
        return {
            "/api/v1/namespaces/ingress-nginx/services/ingress-nginx-controller": {
                "metadata": {"uid": "retained-service"},
                "spec": {"type": "LoadBalancer", "selector": selector,
                         "ports": [{"port": port, "protocol": "TCP", "targetPort": target}
                                   for port, target in [(80, "web"), (443, "websecure"), (22, "ssh")]]},
                "status": {"loadBalancer": {"ingress": [{"ip": dns.ADDRESS}]}}},
            "/api/v1/namespaces/ingress-nginx/configmaps/ingress-traefik-file-provider": {
                "data": {"config.yml": config}},
            "/api/v1/namespaces/gitea/services/gitea-ssh": {
                "spec": {"clusterIP": "None", "ports": [{"port": 22, "protocol": "TCP", "targetPort": 2222}]}},
            "/apis/apps/v1/namespaces/ingress-nginx/deployments/ingress-traefik": {
                "metadata": {"generation": 4},
                "spec": {"replicas": 2, "selector": {"matchLabels": selector},
                         "template": {"spec": {"containers": [{"args": [
                             "--providers.file.directory=/etc/traefik/dynamic",
                             "--providers.kubernetesingressnginx"]}]}}},
                "status": {"observedGeneration": 4, "readyReplicas": 2, "availableReplicas": 2}}}

    def verify(self, objects):
        def read(args):
            self.assertNotIn("apply", args)
            self.assertNotIn("patch", args)
            if "config" in args:
                return b"https://10.0.20.50:6443"
            if "version" in args:
                return json.dumps({"serverVersion": {"major": "1", "minor": "33"},
                                   "clientVersion": {"major": "1", "minor": "34"}}).encode()
            return json.dumps(objects[args[-1]]).encode()
        with patch.object(dns, "run", side_effect=read):
            return dns.verify_ingress()

    def test_retained_public_service_and_headless_target(self):
        result = self.verify(self.fixture())
        self.assertEqual(result["service_uid"], "retained-service")
        self.assertEqual(result["ssh_target"], "gitea-ssh.gitea.svc.cluster.local:2222")

    def test_wrong_address_selector_port_backend_or_unready_rollout_refused(self):
        for fault in ("address", "selector", "port", "backend", "headless", "providers", "readiness", "generation"):
            with self.subTest(fault=fault):
                objects = copy.deepcopy(self.fixture())
                svc = objects["/api/v1/namespaces/ingress-nginx/services/ingress-nginx-controller"]
                deploy = objects["/apis/apps/v1/namespaces/ingress-nginx/deployments/ingress-traefik"]
                if fault == "address":
                    svc["status"]["loadBalancer"]["ingress"][0]["ip"] = "10.0.20.227"
                elif fault == "selector":
                    svc["spec"]["selector"] = {"app.kubernetes.io/name": "ingress-nginx"}
                elif fault == "port":
                    svc["spec"]["ports"][-1]["targetPort"] = "22-tcp"
                elif fault == "backend":
                    cm = objects["/api/v1/namespaces/ingress-nginx/configmaps/ingress-traefik-file-provider"]
                    cm["data"]["config.yml"] = cm["data"]["config.yml"].replace(":2222", ":22")
                elif fault == "headless":
                    objects["/api/v1/namespaces/gitea/services/gitea-ssh"]["spec"]["ports"][0]["targetPort"] = 22
                elif fault == "providers":
                    deploy["spec"]["template"]["spec"]["containers"][0]["args"] = []
                elif fault == "readiness":
                    deploy["status"]["readyReplicas"] = 1
                else:
                    deploy["status"]["observedGeneration"] = 3
                with self.assertRaises(dns.Refusal):
                    self.verify(objects)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="private-dns-tests-", dir=os.environ.get("TMPDIR"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_private_permissions_and_no_overwrite(self):
        path = self.root / "recovery"
        fd = dns.protected_directory(path, create=True)
        self.addCleanup(os.close, fd)
        dns.new_private_file(fd, "backup.xml", b"synthetic fixture")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((path / "backup.xml").stat().st_mode), 0o600)
        with self.assertRaises(FileExistsError):
            dns.new_private_file(fd, "backup.xml", b"replacement")
        self.assertEqual((path / "backup.xml").read_bytes(), b"synthetic fixture")

    def test_symlink_and_existing_unsafe_directory_refused(self):
        link = self.root / "link"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError):
            dns.protected_directory(link)
        path = self.root / "unsafe"
        path.mkdir(mode=0o755)
        with self.assertRaises(dns.Refusal):
            dns.protected_directory(path)

    def test_read_missing_directory_does_not_create_it(self):
        path = self.root / "missing"
        with self.assertRaises(FileNotFoundError):
            dns.read_private(path / "receipt.jsonl")
        self.assertFalse(path.exists())

    def test_wrong_owner_refused(self):
        original = os.fstat
        def wrong_owner(fd):
            values = list(original(fd))
            values[4] = os.getuid() + 10000
            return os.stat_result(values)
        with patch.object(dns.os, "fstat", side_effect=wrong_owner), self.assertRaises(dns.Refusal):
            dns.protected_directory(self.root)


if __name__ == "__main__":
    unittest.main(verbosity=2)
