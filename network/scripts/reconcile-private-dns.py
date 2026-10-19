#!/usr/bin/env python3
"""Check reviewed private DNS records; mutate only with --apply on pushed, scoped-clean master.

See network/docs/network/private-dns.md. No automatic retries or automatic rollback.
Credentials, certificates, cookies and downloaded configuration remain in memory,
except a fresh full configuration backup in the explicitly selected recovery directory.
"""

import argparse
import base64
import copy
import datetime
import hashlib
import html.parser
import http.client
import http.cookiejar
import json
import os
from pathlib import Path
import re
import resource
import socket
import ssl
import stat
import subprocess
import sys
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
DESIRED = ROOT / "network/configs/dnsmasq-private-hosts.json"
SCOPED = ["network/configs/dnsmasq-private-hosts.json", "network/scripts/reconcile-private-dns.py",
          "network/scripts/test_reconcile_private_dns.py", "network/docs/network/private-dns.md",
          "network/docs/index.md"]
ORIGIN = "git@git.eaglepass.io:ops/homelab.git"
VERSION = "25.7.9_7"
CORE_HASH = "c6ffd18ec3f1c07651fe917093e0a53c342b9e24"
MODEL_VERSION = "1.0.8"
ADDRESS = "10.0.20.226"
NAMES = {"git", "registry", "auth", "argocd", "dex", "grafana", "radarr", "sabnzbd", "searxng", "sonarr", "ci"}
VAULT = "4uaua4a45yuhnwhehp5bwylmti"
LOGIN = "tcmshcqbj6c2wkssfvzc6ppvku"
DOCUMENT = "ta2atlxlrcrqkq6kwhgchuqudm"
ROUTER = "10.0.0.1"
TLS_NAME = "opnsense.localdomain"
HOST_FIELDS = {"host", "domain", "ip", "local", "aliases", "cnames", "client_id",
               "hwaddr", "lease_time", "ignore", "set_tag", "descr", "comments"}
SETTINGS = "/api/dnsmasq/settings/get"
SOCKETS = "/api/diagnostics/interface/get_socket_statistics"
ADD = "/api/dnsmasq/settings/add_host"
DELETE = "/api/dnsmasq/settings/del_host/"
RESTART = "/api/dnsmasq/service/restart"
READ_PATHS = {"/", "/diag_backup.php", "/system_advanced_admin.php", SETTINGS, SOCKETS,
              "/api/dnsmasq/settings/get_host", "/api/dnsmasq/service/status",
              "/api/core/firmware/info", "/api/unbound/settings/get",
              "/api/unbound/settings/get_nameservers",
              "/api/interfaces/vlan_settings/get", "/api/interfaces/lagg_settings/get",
              "/api/interfaces/overview/interfaces_info"}
FIREWALL_PATHS = {name: "/firewall_rules.php?if=" + name
                  for name in ("FloatingRules", "wan", "lan", "opt1", "opt2", "opt3", "opt4", "opt5")}
READ_PATHS.update(FIREWALL_PATHS.values())
PF_RULES = "/api/diagnostics/firewall/pf_statistics/rules"
PF_STATES = "/api/diagnostics/firewall/pf_states"
PF_ALIASES = "/api/firewall/alias_util/aliases"
READ_PATHS.update((PF_RULES, PF_STATES, PF_ALIASES))


def pf_snapshot(api):
    """Read active PF/NAT rules; exclude quoted descriptions and state endpoints."""
    value = api.get(PF_RULES)
    require(isinstance(value, dict) and isinstance(value.get("rules"), dict), "Missing active PF rules")
    result = {"rules": {}}
    for kind in ("filter rules", "nat rules"):
        rules = value["rules"].get(kind)
        require(isinstance(rules, dict), "Missing active PF rule section")
        result["rules"][kind] = []
        for text, counters in rules.items():
            require(isinstance(text, str) and text.isascii() and all(ord(c) >= 32 for c in text),
                    "Invalid active PF rule text")
            text = re.sub(r'"(?:[^"\\]|\\.)*"', "<quoted>", text)
            require('"' not in text and isinstance(counters, dict), "Invalid active PF rule projection")
            result["rules"][kind].append({"rule": text})
    require(result["rules"]["filter rules"], "Empty active PF filter rules")
    states = api.get(PF_STATES)
    require(isinstance(states, dict) and set(states) == {"current", "limit"}, "Missing PF state capacity")
    require(all(isinstance(v, str) and v.isascii() and v.isdigit() for v in states.values()),
            "Invalid PF state capacity")
    result["states"] = {k: int(v) for k, v in states.items()}
    require(0 <= result["states"]["current"] <= result["states"]["limit"] and result["states"]["limit"] > 0,
            "PF state capacity exceeded or invalid")
    aliases = api.get(PF_ALIASES)
    require(isinstance(aliases, list) and all(isinstance(a, str) and
            re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", a) for a in aliases), "Invalid active PF alias inventory")
    require(len(set(aliases)) == len(aliases), "Duplicate active PF aliases")
    result["aliases"] = sorted(aliases)
    return result


class FirewallRules(html.parser.HTMLParser):
    """Project rendered rule semantics; discard descriptions, forms and hidden values."""
    def __init__(self, text):
        super().__init__()
        self.rules = []
        self.tables = 0
        self.row = None
        self.cell = None
        self.feed(text)
        self.close()
        require(self.tables > 0 and self.row is None, "Missing or incomplete firewall rule table")

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        classes = set(attrs.get("class", "").split())
        if tag == "table" and "opnsense-rules" in classes:
            self.tables += 1
        if tag == "tr" and "rule" in classes:
            require(self.row is None, "Nested firewall rule row")
            self.row = {"cells": [], "action": None, "enabled": None, "direction": None, "first_match": None}
        elif self.row is not None:
            require(tag not in ("tr", "table"), "Unexpected nested firewall rule markup")
            if tag == "td":
                # The pinned GUI omits closing tags in trailing statistics cells, beyond projected policy fields.
                if self.cell is not None:
                    require(len(self.row["cells"]) >= 9, "Nested firewall policy cell")
                    self.row["cells"].append("")
                self.cell = []
            elif tag in ("i", "span") and len(self.row["cells"]) == 1:
                actions = {"fa-play": "pass", "fa-times": "block", "fa-times-circle": "reject"}
                action = set(actions).intersection(classes)
                if action:
                    require(len(action) == 1 and self.row["action"] is None, "Ambiguous firewall action")
                    icon = action.pop()
                    color = "text-success" if icon == "fa-play" else "text-danger"
                    require(len({color, "text-muted"}.intersection(classes)) == 1,
                            "Ambiguous firewall enabled state")
                    self.row.update(action=actions[icon], enabled="text-muted" not in classes)
                for icon, direction in (("fa-long-arrow-right", "in"), ("fa-long-arrow-left", "out"), ("fa-exchange", "any")):
                    if icon in classes:
                        require(self.row["direction"] is None, "Ambiguous firewall direction")
                        self.row["direction"] = direction
                if "fa-flash" in classes:
                    require(self.row["first_match"] is None and len({"text-warning", "text-muted"}.intersection(classes)) == 1,
                            "Ambiguous firewall match order")
                    self.row["first_match"] = "text-warning" in classes

    def handle_data(self, data):
        if self.row is not None and self.cell is not None and 2 <= len(self.row["cells"]) <= 8:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.row is None:
            return
        if tag == "td":
            require(self.cell is not None, "Unmatched firewall rule cell")
            self.row["cells"].append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr":
            require(self.cell is None and len(self.row["cells"]) >= 10 and
                    all(self.row[k] is not None for k in ("action", "enabled", "direction", "first_match")),
                    "Incomplete firewall rule semantics")
            cells = self.row.pop("cells")
            fields = ("protocol", "source", "source_port", "destination", "destination_port", "gateway", "schedule")
            self.row.update(zip(fields, cells[2:9]))
            require(all(self.row[k] for k in fields), "Empty firewall rule semantic field")
            self.rules.append(self.row)
            self.row = None


def firewall_snapshot(api):
    # Pinned core c6ffd18ec: writes are POST-only; these eight exact GET selectors only render rules.
    return {name: FirewallRules(api.request("GET", path).decode("utf-8")).rules
            for name, path in FIREWALL_PATHS.items()}


def network_snapshot(api):
    """Project only reviewed topology fields; never export interface credentials."""
    result = {}
    for kind, fields in (
        ("vlan", {"if", "tag", "vlanif", "descr"}),
        ("lagg", {"laggif", "members", "proto", "descr"}),
    ):
        value = normalize(api.get("/api/interfaces/" + kind + "_settings/get"))
        require(isinstance(value, dict) and isinstance(value.get(kind), dict), "Missing topology model")
        records = value[kind].get(kind)
        require(isinstance(records, dict), "Missing topology records")
        result[kind] = []
        for key, row in records.items():
            valid_uuid(key)
            require(isinstance(row, dict), "Invalid topology record")
            projected = {k: v for k, v in row.items() if k in fields}
            require(all(isinstance(v, str) for v in projected.values()), "Unexpected topology field type")
            result[kind].append(projected)
    value = api.get("/api/interfaces/overview/interfaces_info")
    require(isinstance(value, dict) and isinstance(value.get("rows"), list), "Missing interface rows")
    require(value.get("total") == len(value["rows"]), "Incomplete interface pagination")
    fields = {"device", "identifier", "description", "status", "enabled", "addr4", "vlan_tag"}
    result["interfaces"] = []
    for row in value["rows"]:
        require(isinstance(row, dict), "Invalid interface row")
        projected = {k: v for k, v in row.items() if k in fields}
        require(all(isinstance(v, (str, bool, int, type(None))) for v in projected.values()),
                "Unexpected interface field type")
        result["interfaces"].append(projected)
    return result


class Refusal(Exception):
    """Only constant, sanitized messages belong in this exception."""


def require(condition, message):
    if not condition:
        raise Refusal(message)


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def run(args, *, env=None, data=None):
    p = subprocess.run(args, input=data, stdin=subprocess.DEVNULL if data is None else None,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT, env=env)
    require(p.returncode == 0, "Subprocess failed; output withheld; no retry")
    return p.stdout


def op_read(kind, item):
    env = os.environ.copy()
    env.pop("XDG_CONFIG_HOME", None)
    env["OP_BIOMETRIC_UNLOCK_ENABLED"] = "false"
    args = ["op", kind, "get", item, "--vault", VAULT]
    if kind == "item":
        args += ["--format", "json"]
    return run(args, env=env)


def normalize(value):
    """Convert API option widgets to their serialized values, preserving list order."""
    if isinstance(value, dict):
        if value and all(isinstance(v, dict) and "selected" in v for v in value.values()):
            return ",".join(k for k, v in value.items() if str(v["selected"]) == "1")
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, list):
        if all(isinstance(v, dict) and "selected" in v for v in value):
            return ",".join(str(i) for i, v in enumerate(value) if str(v["selected"]) == "1")
        return [normalize(v) for v in value]
    return value


def host_map(settings):
    hosts = settings.get("hosts") or {}
    require(isinstance(hosts, dict), "Unexpected host collection schema")
    for key, row in hosts.items():
        valid_uuid(key)
        require(isinstance(row, dict), "Unexpected host row schema")
    return hosts


def valid_uuid(value):
    try:
        parsed = uuid.UUID(value)
        require(str(parsed) == value and parsed.version == 4, "Invalid row UUID")
    except (ValueError, TypeError, AttributeError):
        raise Refusal("Invalid row UUID") from None
    return value


def validate_desired(data):
    require(set(data) == {"firmware_version", "hosts"} and data["firmware_version"] == VERSION,
            "Unexpected desired-state version or fields")
    rows = data["hosts"]
    require(isinstance(rows, list) and len(rows) == len(NAMES), "Exactly the reviewed private host set is required")
    require(all(isinstance(r, dict) and set(r) == {"host", "domain", "ip", "local"} for r in rows),
            "Unexpected desired host fields")
    require({r["host"] for r in rows} == NAMES, "Private host names differ from approved scope")
    require(all(r["domain"] == "eaglepass.io" and r["ip"] == ADDRESS and r["local"] == "0" for r in rows),
            "Private host address, domain or local flag differs from approved scope")
    return rows


def add_payload(row):
    require(row in validate_desired({"firmware_version": VERSION, "hosts": [
        {"host": n, "domain": "eaglepass.io", "ip": ADDRESS, "local": "0"} for n in sorted(NAMES)]}),
        "Unapproved host payload")
    return {"host": dict(row)}


class Forms(html.parser.HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.forms = []
        self.inputs = []
        self.current = None
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "form":
            self.current = {"attrs": attrs, "inputs": {}}
            self.forms.append(self.current)
        elif tag == "input":
            self.inputs.append(attrs)
            if self.current is not None and attrs.get("name"):
                self.current["inputs"][attrs["name"]] = attrs

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


def csrf_fields(form):
    fields = {k: v.get("value", "") for k, v in form["inputs"].items() if v.get("type") == "hidden"}
    require(len(fields) == 1 and all(fields.values()), "Missing or ambiguous normal CSRF form")
    return fields


def same_origin(location):
    target = urllib.parse.urlsplit(urllib.parse.urljoin("https://" + TLS_NAME + "/", location))
    require(target.scheme == "https" and target.hostname == TLS_NAME and target.port in (None, 443)
            and not target.username and not target.password, "Cross-origin redirect or form refused")
    return target


class Router:
    def __init__(self):
        protected = ET.fromstring(op_read("document", DOCUMENT))
        ref = protected.findtext("./system/webgui/ssl-certref")
        certs = [c for c in protected.findall("cert") if c.findtext("refid") == ref]
        require(ref and len(certs) == 1, "Protected GUI certificate reference missing or ambiguous")
        pem = base64.b64decode(certs[0].findtext("crt"), validate=True).decode("ascii")
        self.certificate = ssl.PEM_cert_to_DER_cert(pem)
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.context.load_verify_locations(cadata=pem)
        self.context.check_hostname = True
        self.context.hostname_checks_common_name = False
        self.context.verify_mode = ssl.CERT_REQUIRED
        self.jar = http.cookiejar.CookieJar()
        self.csrf = None
        self.apply = False
        self.denied = False
        self.login_used = False
        self.trust_hash = hashlib.sha256(self.certificate).hexdigest()

    def request(self, method, path, fields=None, *, form=False):
        require(not self.denied, "Authentication or authorization previously rejected; stop")
        login = method == "POST" and path == "/" and not self.login_used
        if method == "GET":
            require(path in READ_PATHS, "Unapproved read endpoint")
        elif login:
            self.login_used = True
        else:
            require(self.apply and method == "POST", "Configuration writes require apply gates")
            require(path in (ADD, RESTART, "/diag_backup.php") or path.startswith(DELETE),
                    "Unapproved write endpoint")
            if path == ADD:
                require(fields == add_payload(fields.get("host", {})), "Unapproved add request")
            elif path.startswith(DELETE):
                valid_uuid(path[len(DELETE):])
                require(fields == {}, "Unexpected delete payload")
            elif path == RESTART:
                require(fields == {}, "Unexpected restart payload")
            else:
                require(fields == {"download": "1", "donotbackuprrd": "1", **self.csrf},
                        "Only full configuration download is permitted")
        headers = {"Referer": "https://" + TLS_NAME + "/", "Origin": "https://" + TLS_NAME,
                   "X-Requested-With": "XMLHttpRequest", "User-Agent": "homelab-private-dns"}
        if self.csrf:
            headers["X-CSRFToken"] = next(iter(self.csrf.values()))
        body = None
        if fields is not None:
            body = (urllib.parse.urlencode(fields) if form else json.dumps(fields)).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        req = urllib.request.Request("https://" + TLS_NAME + path, headers=headers, data=body, method=method)
        self.jar.add_cookie_header(req)
        conn = http.client.HTTPSConnection(TLS_NAME, timeout=30, context=self.context)
        raw = socket.create_connection((ROUTER, 443), timeout=20)
        try:
            conn.sock = self.context.wrap_socket(raw, server_hostname=TLS_NAME)
            require(conn.sock.getpeercert(binary_form=True) == self.certificate, "Live certificate differs from protected certificate")
            conn.request(method, path, body=body, headers=dict(req.header_items()))
            response = conn.getresponse()
            self.jar.extract_cookies(response, req)
            data = response.read()
            location = response.getheader("Location")
            if location:
                same_origin(location)
            self.denied = response.status in (401, 403)
            require(not self.denied, "Authentication or authorization rejected; no retry")
            if login:
                require(response.status in (302, 303) and location and "password" not in location
                        and "user_portal" not in location, "Login not confirmed; no retry")
            else:
                require(response.status == 200 and not location, "Request failed; response withheld; no retry")
            return data
        finally:
            conn.close()
            raw.close()

    def login(self):
        page = Forms(self.request("GET", "/").decode())
        forms = [f for f in page.forms if f["attrs"].get("method", "").lower() == "post"
                 and {"usernamefld", "passwordfld"}.issubset(f["inputs"])]
        require(len(forms) == 1 and self.jar, "Normal login form or session missing")
        target = same_origin(forms[0]["attrs"].get("action", ""))
        require(target.path == "/" and not target.query, "Unexpected login form action")
        self.csrf = csrf_fields(forms[0])
        credential = json.loads(op_read("item", LOGIN))
        values = {f.get("purpose"): f.get("value") for f in credential.get("fields", [])}
        require(values.get("USERNAME") and values.get("PASSWORD"), "Existing login fields missing")
        self.request("POST", "/", {**self.csrf, "usernamefld": values["USERNAME"],
                     "passwordfld": values["PASSWORD"], "login": "1"}, form=True)

    def get(self, path):
        return json.loads(self.request("GET", path))

    def post(self, path, fields):
        return json.loads(self.request("POST", path, fields))

    def backup(self):
        page = Forms(self.request("GET", "/diag_backup.php").decode())
        forms = [f for f in page.forms if "download" in f["inputs"]]
        require(len(forms) == 1, "Supported backup download form missing")
        target = same_origin(forms[0]["attrs"].get("action", "/diag_backup.php"))
        require(target.path == "/diag_backup.php" and not target.query, "Unexpected backup form action")
        self.csrf = csrf_fields(forms[0])
        return self.request("POST", "/diag_backup.php", {**self.csrf, "download": "1", "donotbackuprrd": "1"}, form=True)


def snapshot(api):
    firmware = api.get("/api/core/firmware/info")
    require(firmware.get("product_id") == "opnsense" and firmware.get("product_version") == VERSION,
            "Unsupported running firmware version")
    product = firmware.get("product", {})
    core_hash = product.get("product_hash", "")
    require(isinstance(core_hash, str) and 7 <= len(core_hash) <= 40 and CORE_HASH.startswith(core_hash),
            "Missing or unexpected firmware source hash")
    defaults = normalize(api.get("/api/dnsmasq/settings/get_host").get("host"))
    require(isinstance(defaults, dict) and set(defaults) == HOST_FIELDS and defaults["local"] == "0",
            "Running host model differs from reviewed schema")
    dnsmasq = normalize(api.get(SETTINGS).get("dnsmasq"))
    require(isinstance(dnsmasq, dict) and dnsmasq.get("enable") == "1" and dnsmasq.get("dns_port") == "53",
            "Dnsmasq is not the expected DNS service")
    dnsmasq["hosts"] = host_map(dnsmasq)
    require(api.get("/api/dnsmasq/service/status").get("status") == "running", "Dnsmasq is not running")
    page = Forms(api.request("GET", "/system_advanced_admin.php").decode())
    flags = [v for v in page.inputs if v.get("name") == "nodnsrebindcheck"]
    require(len(flags) == 1, "Global rebinding setting not found")
    require("checked" not in flags[0], "Global DNS rebinding protection is disabled")
    sockets = api.get(SOCKETS).get("statistics", {}).get("Active Internet connections", {})
    require(isinstance(sockets, dict), "Unexpected socket inventory schema")
    dns, dhcp = [], []
    for row in sockets.values():
        local = row.get("local", {})
        if isinstance(local, dict) and str(local.get("port")) in ("53", "67", "547"):
            item = {k: row.get(k) for k in ("protocol", "command", "pid")}
            item.update(address=local.get("address"), port=str(local["port"]))
            (dns if item["port"] == "53" else dhcp).append(item)
    require(dns and all(r["command"] == "dnsmasq" for r in dns), "Unexpected port 53 owner")
    require(any(r["protocol"] == "udp4" and r["address"] in ("*", "10.0.20.1") for r in dns),
            "Cluster DNS listener not found")
    require(not dnsmasq.get("dhcp_ranges") and dnsmasq.get("dhcp", {}).get("enable_ra") == "0"
            and all(r["command"] != "dnsmasq" for r in dhcp),
            "Dnsmasq serves DHCP/RA; stop/start impact requires separate planning")
    return {"version": VERSION, "source_hash": core_hash, "defaults": defaults, "dnsmasq": dnsmasq,
            "unbound": normalize(api.get("/api/unbound/settings/get")),
            "nameservers": normalize(api.get("/api/unbound/settings/get_nameservers")),
            "rebind_protection": True, "dhcp_sockets": sorted(dhcp, key=lambda r: json.dumps(r, sort_keys=True))}


def plan(state, rows):
    hosts = host_map(state["dnsmasq"])
    missing = []
    for desired in rows:
        fqdn = desired["host"] + "." + desired["domain"]
        matches = []
        for key, row in hosts.items():
            name = str(row.get("host", "")).lower()
            domain = str(row.get("domain", "")).lower().rstrip(".")
            aliases = [a.rstrip(".") for a in (str(row.get("aliases", "")) + "," + str(row.get("cnames", ""))).lower().split(",")]
            require(not {fqdn, desired["host"]}.intersection(aliases), "Existing alias conflicts with a private host")
            require(not (name == "*" and (domain == "eaglepass.io" or not domain)), "Existing wildcard overlaps private hosts")
            if name == desired["host"]:
                require(domain == desired["domain"] and all(row.get(k) == v for k, v in desired.items()),
                        "Existing host conflicts with desired record")
                require(all(not row.get(k) for k in ("hwaddr", "client_id", "cnames", "aliases", "set_tag", "lease_time"))
                        and row.get("ignore", "0") == "0", "Existing private host has non-DNS bindings")
                matches.append(key)
        require(len(matches) <= 1, "Duplicate private host rows")
        if not matches:
            missing.append(desired)
    return missing


def git_gate():
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes"}
    def git(*args):
        return run(["git", *args], env=env).decode().strip()
    require(Path(git("rev-parse", "--show-toplevel")) == ROOT, "Wrong checkout root")
    require(git("remote", "get-url", "origin") == ORIGIN, "Wrong canonical remote")
    require(git("branch", "--show-current") == "master", "Apply requires master")
    require(not git("status", "--porcelain", "--untracked-files=all", "--", *SCOPED), "Scoped files are not clean")
    for path in SCOPED:
        require((ROOT / path).is_file() and not (ROOT / path).is_symlink(), "Scoped source missing or symlinked")
        git("ls-files", "--error-unmatch", path)
    head = git("rev-parse", "HEAD")
    remote = git("ls-remote", "--exit-code", "origin", "refs/heads/master").split()
    require(len(remote) == 2 and remote[0] == head, "HEAD is not pushed canonical master")
    return head


def verify_ingress():
    base = ["kubectl", "--kubeconfig", str(ROOT / "metal/kubeconfig.yaml"), "--request-timeout=30s"]
    server = run(base + ["config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}"]).decode()
    require(server == "https://10.0.20.50:6443", "Wrong Kubernetes API target")
    versions = json.loads(run(base + ["version", "-o", "json"]))
    require(versions["serverVersion"]["major"] == "1" and versions["serverVersion"]["minor"] == "33"
            and versions["clientVersion"]["major"] == "1" and int(versions["clientVersion"]["minor"]) in (32, 33, 34),
            "Unsupported Kubernetes client/server skew")
    def get(path):
        return json.loads(run(base + ["get", "--raw", path]))
    svc = get("/api/v1/namespaces/ingress-nginx/services/ingress-nginx-controller")
    require(svc["spec"]["type"] == "LoadBalancer" and
            {v.get("ip") for v in svc["status"]["loadBalancer"]["ingress"]} == {ADDRESS}, "Ingress IP ownership changed")
    expected_selector = {"app.kubernetes.io/name": "traefik",
                         "app.kubernetes.io/instance": "ingress-nginx-ingress-nginx"}
    require(svc["spec"].get("selector") == expected_selector, "Ingress controller ownership changed")
    ports = {p["port"]: (p["protocol"], p["targetPort"]) for p in svc["spec"]["ports"]}
    require(ports == {80: ("TCP", "web"), 443: ("TCP", "websecure"), 22: ("TCP", "ssh")},
            "Ingress public port bindings changed")
    cm = get("/api/v1/namespaces/ingress-nginx/configmaps/ingress-traefik-file-provider")
    # Fail closed if the pinned chart changes this reviewed file-provider representation.
    expected_config = """tcp:
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
    require(cm.get("data") == {"config.yml": expected_config}, "Gitea SSH route changed")
    gitea = get("/api/v1/namespaces/gitea/services/gitea-ssh")
    require(gitea["spec"].get("clusterIP") == "None" and
            any(p["port"] == 22 and p["protocol"] == "TCP" and p["targetPort"] == 2222
                for p in gitea["spec"]["ports"]), "Headless Gitea SSH target changed")
    deploy = get("/apis/apps/v1/namespaces/ingress-nginx/deployments/ingress-traefik")
    require(deploy["spec"]["selector"]["matchLabels"] == expected_selector, "Ingress Deployment ownership changed")
    args = [a for c in deploy["spec"]["template"]["spec"]["containers"] for a in c.get("args", [])]
    require("--providers.file.directory=/etc/traefik/dynamic" in args and
            "--providers.kubernetesingressnginx" in args, "Controller does not consume the expected providers")
    desired, status = deploy["spec"].get("replicas", 1), deploy.get("status", {})
    require(desired > 0 and status.get("observedGeneration", 0) >= deploy["metadata"]["generation"] and
            status.get("availableReplicas", 0) >= desired and status.get("readyReplicas", 0) >= desired,
            "Ingress controller rollout is not ready")
    return {"service_uid": svc["metadata"]["uid"], "address": ADDRESS,
            "ssh_target": "gitea-ssh.gitea.svc.cluster.local:2222"}



def protected_directory(path, *, create=False):
    """Walk with directory descriptors; never follow links or chmod existing paths."""
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts, "Recovery directory must be absolute")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            require(info.st_uid in (0, os.getuid()) and not info.st_mode & 0o022,
                    "Recovery ancestry has unsafe ownership or write permissions")
        info = os.fstat(fd)
        require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o700,
                "Recovery directory must be owned by current user with mode 0700")
        return fd
    except BaseException:
        os.close(fd)
        raise


def new_private_file(directory_fd, name, data):
    require(Path(name).name == name, "Invalid recovery filename")
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_nlink == 1, "Unsafe recovery file")
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
        os.fsync(directory_fd)
    finally:
        os.close(fd)


def xml_values(node):
    if len(node) == 0:
        return node.text or ""
    result = {}
    for child in node:
        if "uuid" in child.attrib:
            result.setdefault(child.tag, {})[child.attrib["uuid"]] = xml_values(child)
        else:
            require(child.tag not in result, "Unexpected repeated backup field")
            result[child.tag] = xml_values(child)
    return result


def validate_backup(data, state, certificate_hash):
    root = ET.fromstring(data)
    require(root.tag == "opnsense" and root.findtext("system/hostname", "").lower() == "opnsense"
            and root.findtext("system/domain", "").lower() == "localdomain", "Backup router identity mismatch")
    ref = root.findtext("system/webgui/ssl-certref")
    certs = [c for c in root.findall("cert") if c.findtext("refid") == ref]
    require(len(certs) == 1, "Backup certificate identity missing")
    der = ssl.PEM_cert_to_DER_cert(base64.b64decode(certs[0].findtext("crt"), validate=True).decode())
    require(hashlib.sha256(der).hexdigest() == certificate_hash, "Backup certificate mismatch")
    node = root.find("dnsmasq")
    require(node is not None and node.get("version") == MODEL_VERSION, "Backup Dnsmasq model version mismatch")
    require(root.find("system/webgui/nodnsrebindcheck") is None, "Backup rebinding protection differs")
    stored = xml_values(node)
    require(isinstance(stored, dict), "Backup Dnsmasq section missing")
    def compare(saved, live):
        if isinstance(saved, dict):
            require(isinstance(live, dict), "Backup settings differ from live model")
            for k, v in saved.items():
                require(k in live, "Backup contains an unknown model field")
                compare(v, live[k])
        else:
            require(saved == live or (not saved and not live), "Backup settings differ from live model")
    compare(stored, state["dnsmasq"])
    require(set(stored.get("hosts") or {}) == set(host_map(state["dnsmasq"])), "Backup host UUID inventory differs")
    return root


def guard(api, expected):
    current = snapshot(api)
    require(sha(current) == sha(expected), "Live settings drifted; stop before next write")
    return current


def reconcile(api, expected, rows, record):
    """One add per missing name, exact readback, then one persisted-state restart."""
    for row in plan(expected, rows):
        guard(api, expected)
        record({"event": "before_add", "hostname": row["host"] + ".eaglepass.io", "state_sha256": sha(expected)})
        response = api.post(ADD, add_payload(row))
        require(response.get("result") == "saved", "Host add did not return saved; no retry")
        key = valid_uuid(response.get("uuid"))
        require(key not in host_map(expected["dnsmasq"]), "Add returned an existing UUID")
        record({"event": "add_acknowledged", "uuid": key, "hostname": row["host"] + ".eaglepass.io"})
        predicted = copy.deepcopy(expected)
        predicted["dnsmasq"]["hosts"][key] = {**expected["defaults"], **row}
        actual = snapshot(api)
        require(sha(actual) == sha(predicted), "Add readback differs; inspect receipt; no retry")
        expected = actual
        record({"event": "created", "uuid": key, "hostname": row["host"] + ".eaglepass.io",
                "row_sha256": sha(expected["dnsmasq"]["hosts"][key]), "state_sha256": sha(expected)})
    guard(api, expected)
    record({"event": "before_restart", "state_sha256": sha(expected)})
    require(api.post(RESTART, {}) == {"response": "OK"}, "Restart failed or uncertain; no retry")
    guard(api, expected)
    record({"event": "complete", "state_sha256": sha(expected)})
    return expected


def rollback_plan(events, state, backup):
    require(events and events[0].get("event") == "backup" and events[-1].get("event") == "complete",
            "Automatic rollback requires a complete verified apply receipt; partial runs need investigation")
    require(events[-1]["state_sha256"] == sha(state), "Rollback state drifted")
    require(hashlib.sha256(backup).hexdigest() == events[0].get("backup_sha256"), "Rollback backup hash differs")
    old = ET.fromstring(backup).find("dnsmasq")
    require(old is not None, "Rollback backup lacks Dnsmasq")
    prior = {h.get("uuid") for h in old.findall("hosts")}
    created = [e for e in events if e.get("event") == "created"]
    require(0 < len(created) <= len(NAMES) and len({e["uuid"] for e in created}) == len(created), "Invalid rollback UUID scope")
    hosts = host_map(state["dnsmasq"])
    for event in created:
        key = valid_uuid(event["uuid"])
        require(key not in prior and key in hosts and sha(hosts[key]) == event["row_sha256"], "Rollback row ownership or contents changed")
        require(event["hostname"] in {n + ".eaglepass.io" for n in NAMES}, "Rollback hostname outside scope")
        row = hosts[key]
        require(row["host"] + "." + row["domain"] == event["hostname"] and row["ip"] == ADDRESS and row["local"] == "0",
                "Rollback target differs from owned private host")
    require(set(hosts) - {e["uuid"] for e in created} == prior, "Unowned host UUID inventory changed")
    return created


def rollback(api, expected, targets, record):
    for event in reversed(targets):
        guard(api, expected)
        key = event["uuid"]
        record({"event": "before_delete", "uuid": key, "state_sha256": sha(expected)})
        require(api.post(DELETE + key, {}).get("result") == "deleted", "Delete failed or uncertain; no retry")
        predicted = copy.deepcopy(expected)
        del predicted["dnsmasq"]["hosts"][key]
        actual = snapshot(api)
        require(sha(actual) == sha(predicted), "Delete readback differs; no retry")
        expected = actual
        record({"event": "deleted", "uuid": key, "state_sha256": sha(expected)})
    guard(api, expected)
    record({"event": "before_restart", "state_sha256": sha(expected)})
    require(api.post(RESTART, {}) == {"response": "OK"}, "Rollback restart failed or uncertain; no retry")
    guard(api, expected)
    record({"event": "rollback_complete", "state_sha256": sha(expected)})


def read_private(path):
    fd = protected_directory(path.parent)
    try:
        file_fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == 0o600
                    and info.st_nlink == 1, "Unsafe recovery input")
            return stream.read()
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--network-audit", action="store_true", help="Read-only VLAN, LAG and interface projection")
    parser.add_argument("--firewall-audit", action="store_true", help="Read-only rendered firewall policy projection")
    parser.add_argument("--pf-audit", action="store_true", help="Read-only active PF/NAT rules and state capacity")
    parser.add_argument("--backup-dir", type=Path, help="Explicit private, durable recovery directory; only used for apply")
    parser.add_argument("--rollback-receipt", type=Path, help="Exact complete apply JSONL receipt; default only checks rollback")
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.umask(0o077)
    result = {"mode": "apply" if args.apply else "check", "events": []}
    api = None
    journal = None
    journal_broken = False
    directory_fd = None
    initial = None
    mutation_started = False
    def record(event):
        nonlocal journal_broken
        result["events"].append(event)
        if journal is not None and not journal_broken:
            try:
                journal.write(json.dumps(event, sort_keys=True) + "\n")
                journal.flush()
                os.fsync(journal.fileno())
            except OSError:
                journal_broken = True
                raise Refusal("Recovery receipt write failed; stop; no retry") from None
    try:
        require(not (args.network_audit or args.firewall_audit or args.pf_audit) or not (args.apply or args.backup_dir or args.rollback_receipt),
                "Network audit cannot apply or access recovery files")
        rows = validate_desired(json.loads(DESIRED.read_text()))
        head = git_gate() if args.apply else run(["git", "rev-parse", "HEAD"]).decode().strip()
        result.update(source_head=head, desired_sha256=sha(rows), ingress=verify_ingress(),
                      source_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SCOPED})
        api = Router()
        api.login()
        initial = snapshot(api)
        missing = plan(initial, rows)
        result.update(firmware_version=initial["version"], firmware_source_hash=initial["source_hash"],
                      state_sha256=sha(initial), certificate_sha256=api.trust_hash,
                      missing=[r["host"] + ".eaglepass.io" for r in missing],
                      preserved_sha256=sha({**initial, "dnsmasq": {k: v for k, v in initial["dnsmasq"].items() if k != "hosts"}}))
        if args.network_audit:
            result.update(mode="read-only-network-audit", topology=network_snapshot(api), status="CHECKED")
        if args.firewall_audit:
            result.update(mode="read-only-firewall-audit", firewall=firewall_snapshot(api), status="CHECKED")
        if args.pf_audit:
            result.update(mode="read-only-pf-audit", pf=pf_snapshot(api), status="CHECKED")
        if args.network_audit or args.firewall_audit or args.pf_audit:
            return 0
        targets = None
        if args.rollback_receipt:
            events = [json.loads(line) for line in read_private(args.rollback_receipt).splitlines()]
            name = events[0]["backup_file"]
            require(Path(name).name == name, "Unsafe rollback backup reference")
            targets = rollback_plan(events, initial, read_private(args.rollback_receipt.parent / name))
            result["rollback_uuids"] = [t["uuid"] for t in targets]
        if not args.apply or (not missing and targets is None):
            result["status"] = "CHECKED" if not args.apply else "ALREADY_CONFIGURED"
            return 0
        require(args.backup_dir is not None, "Apply requires an explicit protected recovery directory")
        absolute = args.backup_dir.absolute()
        recovery_root = Path.home() / ".local/state/homelab/recovery/opnsense"
        require(absolute == recovery_root or recovery_root in absolute.parents,
                "Backup must be inside the operator's durable homelab recovery directory")
        forbidden = [ROOT] + [Path(os.environ[k]).absolute() for k in ("TMPDIR", "TMP", "TEMP", "XDG_CACHE_HOME") if os.environ.get(k)]
        require(not any(absolute == p or p in absolute.parents for p in forbidden), "Recovery directory is source or disposable storage")
        directory_fd = protected_directory(absolute, create=True)
        require(git_gate() == head, "Source changed during preflight")
        guard(api, initial)
        api.apply = True
        backup = api.backup()
        validate_backup(backup, initial, api.trust_hash)
        guard(api, initial)
        batch = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
        backup_name, journal_name = batch + ".xml", batch + ".jsonl"
        result["recovery_backup_file"] = str(absolute / backup_name)
        new_private_file(directory_fd, backup_name, backup)
        new_private_file(directory_fd, journal_name, b"")
        journal = os.fdopen(os.open(journal_name, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW, dir_fd=directory_fd), "a")
        result["recovery_receipt"] = str(absolute / journal_name)
        record({"event": "backup", "backup_file": backup_name, "backup_sha256": hashlib.sha256(backup).hexdigest(),
                "source_head": head, "desired_sha256": sha(rows), "state_sha256": sha(initial), "model_version": MODEL_VERSION,
                "firmware_version": VERSION, "certificate_sha256": api.trust_hash})
        mutation_started = True
        if targets is None:
            reconcile(api, initial, rows, record)
        else:
            rollback(api, initial, targets, record)
        result["status"] = "CONFIGURATION_VERIFIED_APPLICATION_GATES_PENDING"
        return 0
    except (Exception, KeyboardInterrupt) as error:
        result.update(status="BLOCKED_INCOMPLETE", error=str(error) if isinstance(error, Refusal) else type(error).__name__)
        if mutation_started and api is not None and not api.denied:
            try:
                observed = snapshot(api)
                before = host_map(initial["dnsmasq"])
                after = host_map(observed["dnsmasq"])
                record({"event": "failure_readback", "state_sha256": sha(observed),
                        "new_uuids": sorted(set(after) - set(before)), "removed_uuids": sorted(set(before) - set(after)),
                        "manual_investigation_required": True})
            except Exception:
                record({"event": "failure_readback_unavailable", "manual_investigation_required": True})
        return 1
    finally:
        close_failed = False
        if api is not None:
            api.jar.clear()
        if journal is not None:
            try:
                journal.close()
            except OSError:
                close_failed = True
                result.update(status="BLOCKED_INCOMPLETE", error="Recovery receipt close failed")
        if directory_fd is not None:
            os.close(directory_fd)
        print(json.dumps(result, indent=2))
        if close_failed:
            return 1


if __name__ == "__main__":
    sys.exit(main())
