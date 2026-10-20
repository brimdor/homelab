#!/usr/bin/env python3
"""Qualify Cilium LB-IPAM and L2 ownership only in an owned synthetic cluster."""

import ipaddress
import inspect
import json
import re
import socket
import struct
import time

from cilium_qualification import CHARTS


IMAGE = "docker.io/library/python:3.13-alpine@sha256:2d9aefe2fef018a7eb2c13064c89c71929800fd2e5dccdbf52ea5da5bb8d929a"
NETWORK = "172.31.240.0/24"
CIDR = "172.31.240.224/27"
VIP = "172.31.240.226"
NAMESPACE = "qualification-l2"
NAME = "qualification-l2"
LABEL = "qualification.eaglepass.io/l2"
PAYLOAD = b'{"maintenance":"103","service":"qualification-l2"}\n'


def arp_response(raw, target):
    if (len(raw) >= 42 and raw[12:14] == b"\x08\x06" and
            raw[14:22] == struct.pack("!HHBBH", 1, 0x0800, 6, 4, 2) and
            raw[28:32] == socket.inet_aton(target) and raw[6:12] == raw[22:28]):
        return ":".join(format(x, "02x") for x in raw[22:28])
    return None


SERVER = '''from http.server import BaseHTTPRequestHandler,HTTPServer
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  body=PAYLOAD
  self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def log_message(self,*args):pass
HTTPServer(('0.0.0.0',8080),Handler).serve_forever()
'''.replace("body=PAYLOAD", "body=" + repr(PAYLOAD))

# The external caller has NET_RAW only. No static ARP entry or node route is injected.
PROBE = '''import socket,struct,fcntl,time,json,urllib.request
s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(0x0806));s.bind(('eth0',0))
try:
 mac=s.getsockname()[4];ctl=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
 try:src=fcntl.ioctl(ctl.fileno(),0x8915,struct.pack('256s',b'eth0'))[20:24]
 finally:ctl.close()
 ip=socket.inet_aton(VIP);packet=b'\\xff'*6+mac+struct.pack('!H',0x0806)+struct.pack('!HHBBH',1,0x0800,6,4,1)+mac+src+b'\\0'*6+ip
 responses=set();end=time.monotonic()+2;s.settimeout(0.2)
 while time.monotonic()<end:
  s.send(packet)
  try:
   raw=s.recv(2048)
   response=arp_response(raw,VIP)
   if response:responses.add(response)
  except socket.timeout:pass
finally:s.close()
responses_http=[]
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for _ in range(10):
 with opener.open('http://'+VIP+':8080/',timeout=5) as r:
  body=r.read(1024)
  if r.status!=200 or body!=PAYLOAD:raise RuntimeError('wrong synthetic HTTP response')
  responses_http.append(r.status)
print(json.dumps({'vip':VIP,'arp_macs':sorted(responses),'http_statuses':responses_http}))
'''.replace("VIP", repr(VIP)).replace("PAYLOAD", repr(PAYLOAD))
PROBE = "import socket,struct\n" + inspect.getsource(arp_response) + "\n" + PROBE


def validate_probe(result, mac):
    if (result.get("vip") != VIP or result.get("arp_macs") != [mac.lower()] or
            result.get("http_statuses") != [200] * 10):
        raise RuntimeError("external ARP/HTTP evidence is missing, ambiguous or wrong")


def validate_pool(pool, uid, *, migrated):
    spec = pool.get("spec", {})
    field = "blocks" if migrated else "cidrs"
    if (not uid or pool.get("metadata", {}).get("uid") != uid or
            spec.get(field) != [{"cidr": CIDR}] or spec.get("allowFirstLastIPs") != "No" or
            (migrated and "cidrs" in spec)):
        raise RuntimeError("synthetic pool identity or usable range changed")


def validate_service(service, uid):
    if (not uid or service.get("metadata", {}).get("uid") != uid or
            service.get("spec", {}).get("type") != "LoadBalancer" or
            service.get("spec", {}).get("externalTrafficPolicy") != "Cluster" or
            service.get("status", {}).get("loadBalancer", {}).get("ingress") != [{"ip": VIP}]):
        raise RuntimeError("synthetic Service identity, traffic policy or VIP changed")


def validate_lease(lease, nodes, *, previous=None):
    meta, spec = lease.get("metadata", {}), lease.get("spec", {})
    if (not meta.get("uid") or spec.get("holderIdentity") not in nodes or
            type(spec.get("leaseTransitions")) is not int or not spec.get("renewTime")):
        raise RuntimeError("synthetic lease evidence is incomplete")
    if previous and (meta["uid"] != previous["metadata"]["uid"] or
                     spec["holderIdentity"] == previous["spec"]["holderIdentity"] or
                     spec["leaseTransitions"] <= previous["spec"]["leaseTransitions"]):
        raise RuntimeError("same synthetic lease did not transfer to another node")


def migration_patch(pool):
    uid = pool.get("metadata", {}).get("uid")
    validate_pool(pool, uid, migrated=False)
    if "blocks" in pool["spec"] or not pool["metadata"].get("resourceVersion"):
        raise RuntimeError("unexpected pre-migration pool")
    return [{"op": "test", "path": "/metadata/uid", "value": uid},
            {"op": "test", "path": "/metadata/resourceVersion", "value": pool["metadata"]["resourceVersion"]},
            {"op": "test", "path": "/spec/cidrs", "value": [{"cidr": CIDR}]},
            {"op": "add", "path": "/spec/blocks", "value": [{"cidr": CIDR}]},
            {"op": "remove", "path": "/spec/cidrs"}]


def manifest():
    labels = {"app": NAME, LABEL: "true"}
    return {"apiVersion": "v1", "kind": "List", "items": [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NAMESPACE}},
        {"apiVersion": "cilium.io/v2alpha1", "kind": "CiliumLoadBalancerIPPool",
         "metadata": {"name": NAME}, "spec": {"cidrs": [{"cidr": CIDR}], "allowFirstLastIPs": "No",
                                                 "serviceSelector": {"matchLabels": {LABEL: "true"}}}},
        {"apiVersion": "cilium.io/v2alpha1", "kind": "CiliumL2AnnouncementPolicy",
         "metadata": {"name": NAME}, "spec": {"serviceSelector": {"matchLabels": {LABEL: "true"}},
                                                "nodeSelector": {"matchLabels": {LABEL: "true"}},
                                                "interfaces": ["^eth0$"], "loadBalancerIPs": True}},
        {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": NAME, "namespace": NAMESPACE},
         "spec": {"replicas": 3, "selector": {"matchLabels": labels}, "template": {
             "metadata": {"labels": labels}, "spec": {"automountServiceAccountToken": False,
                 "securityContext": {"runAsUser": 65532, "runAsGroup": 65532, "runAsNonRoot": True,
                                     "seccompProfile": {"type": "RuntimeDefault"}},
                 "affinity": {"podAntiAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": [
                     {"labelSelector": {"matchLabels": labels}, "topologyKey": "kubernetes.io/hostname"}]}},
                 "containers": [{"name": "http", "image": IMAGE, "command": ["python3", "-B", "-c", SERVER],
                                 "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                                     "capabilities": {"drop": ["ALL"]}},
                                 "readinessProbe": {"httpGet": {"path": "/", "port": 8080}}}]}}}},
        {"apiVersion": "v1", "kind": "Service", "metadata": {"name": NAME, "namespace": NAMESPACE,
             "labels": {LABEL: "true"}},
         "spec": {"type": "LoadBalancer", "loadBalancerIP": VIP, "externalTrafficPolicy": "Cluster", "selector": labels,
                  "ports": [{"port": 8080, "targetPort": 8080}]}}]}


def await_value(read, accept, description, seconds=180):
    deadline = time.monotonic() + seconds
    while True:
        value = read()
        if accept(value):
            return value
        if time.monotonic() >= deadline:
            raise RuntimeError("timed out waiting for " + description)
        time.sleep(1)


class L2Qualification:
    def __init__(self, qualification):
        self.q = qualification
        self.nodes = {}
        self.pool_uid = self.service_uid = None
        self.client = qualification.args.name + "-l2-client"
        self.stages = []

    def get_pool(self):
        return self.q.kubectl("get", "ciliumloadbalancerippool", NAME)

    def get_service(self):
        return self.q.kubectl("get", "service", NAME, "-n", NAMESPACE)

    def get_lease(self):
        return self.q.kubectl("get", "lease", "cilium-l2announce-" + NAMESPACE + "-" + NAME, "-n", "kube-system")

    def external(self, lease):
        self.q.identity()
        # Verify actual source container/network identity immediately before every probe.
        client = json.loads(self.q.command(["docker", "inspect", self.client], private=True))[0]
        net = client["NetworkSettings"]["Networks"]
        if (set(net) != {"k3d-" + self.q.args.name} or client["Mounts"] or
                client["HostConfig"]["Privileged"] or client["HostConfig"]["CapAdd"] != ["NET_RAW"] or
                net["k3d-" + self.q.args.name]["IPAddress"] != "172.31.240.10"):
            raise RuntimeError("external synthetic caller isolation changed")
        result = json.loads(self.q.command(["docker", "exec", self.client, "python3", "-B", "-c", PROBE]))
        validate_probe(result, self.nodes[lease["spec"]["holderIdentity"]])
        return result

    def stage(self, version, phase, *, migrated=True):
        q = self.q
        q.identity()
        print(json.dumps({"l2_phase": phase, "version": version}), flush=True)
        q.command([q.args.cilium, "--kubeconfig", q.env["KUBECONFIG"], "--context", q.context,
                   "status", "--wait", "--wait-duration=10m", "--interactive=false"])
        pods = q.kubectl("get", "pods", "-n", "kube-system", "-l", "k8s-app=cilium")["items"]
        if len(pods) != 3 or any(not all(c["ready"] for c in p["status"]["containerStatuses"]) for p in pods):
            raise RuntimeError("three ready synthetic agents required")
        for pod in pods:
            raw = q.kubectl("exec", "-n", "kube-system", pod["metadata"]["name"], "--",
                            "cilium-dbg", "version", json_output=False)
            if not re.search(rb"\b" + re.escape(version.encode()) + rb"\b", raw):
                raise RuntimeError("native L2 agent version mismatch")
        validate_pool(self.get_pool(), self.pool_uid, migrated=migrated)
        validate_service(self.get_service(), self.service_uid)
        endpoints = q.kubectl("get", "endpointslice", "-n", NAMESPACE, "-l", "kubernetes.io/service-name=" + NAME)
        ready = [e for s in endpoints["items"] for e in s.get("endpoints", []) if e.get("conditions", {}).get("ready")]
        if len(ready) != 3 or {e["nodeName"] for e in ready} != set(self.nodes):
            raise RuntimeError("three ready synthetic backend nodes required")
        first = self.get_lease()
        validate_lease(first, self.nodes)
        before = self.external(first)
        holder = first["spec"]["holderIdentity"]
        q.kubectl("label", "node", holder, LABEL + "=false", "--overwrite", json_output=False)
        try:
            def moved(lease):
                return (lease["spec"].get("holderIdentity") in self.nodes and
                        lease["spec"]["holderIdentity"] != holder and
                        lease["spec"].get("leaseTransitions", 0) > first["spec"]["leaseTransitions"])
            second = await_value(self.get_lease, moved, "synthetic L2 lease transfer")
            validate_lease(second, self.nodes, previous=first)
            after = self.external(second)
        finally:
            q.kubectl("label", "node", holder, LABEL + "=true", "--overwrite", json_output=False)
        validate_pool(self.get_pool(), self.pool_uid, migrated=migrated)
        validate_service(self.get_service(), self.service_uid)
        self.stages.append({"phase": phase, "version": version, "cluster_uid": q.cluster_uid,
                            "pool_uid": self.pool_uid, "service_uid": self.service_uid,
                            "lease_uid": first["metadata"]["uid"], "before": before, "after": after,
                            "old_holder": holder, "new_holder": second["spec"]["holderIdentity"],
                            "lease_transitions": second["spec"]["leaseTransitions"]})
        (q.work / "l2-progress.json").write_text(json.dumps(self.stages, indent=2))

    def run(self):
        q = self.q
        q.create()
        values = q.work / "values.yaml"
        import yaml
        config = yaml.safe_load(values.read_text())
        config["devices"] = ["eth0"]
        values.write_text(yaml.safe_dump(config))
        q.install("1.15.1")
        q.command([q.args.cilium, "--kubeconfig", q.env["KUBECONFIG"], "--context", q.context,
                   "status", "--wait", "--wait-duration=10m", "--interactive=false"])
        network = json.loads(q.command(["docker", "network", "inspect", "k3d-" + q.args.name], private=True))[0]
        if [c["Subnet"] for c in network["IPAM"]["Config"]] != [NETWORK]:
            raise RuntimeError("synthetic bridge subnet changed")
        allocated = {str(ipaddress.ip_interface(c["IPv4Address"]).ip) for c in network["Containers"].values()}
        if "172.31.240.10" in allocated or any(ipaddress.ip_address(x) in ipaddress.ip_network(CIDR) for x in allocated):
            raise RuntimeError("synthetic caller or VIP pool collides with Docker allocation")
        for node in q.kubectl("get", "nodes")["items"]:
            name = node["metadata"]["name"]
            data = json.loads(q.command(["docker", "inspect", name], private=True))[0]
            self.nodes[name] = data["NetworkSettings"]["Networks"]["k3d-" + q.args.name]["MacAddress"].lower()
            q.kubectl("label", "node", name, LABEL + "=true", "--overwrite", json_output=False)
        q.kubectl("apply", "-f", "-", data=json.dumps(manifest()).encode(), json_output=False)
        self.pool_uid = self.get_pool()["metadata"]["uid"]
        self.service_uid = self.get_service()["metadata"]["uid"]
        await_value(self.get_service, lambda s: s.get("status", {}).get("loadBalancer", {}).get("ingress") == [{"ip": VIP}], "synthetic VIP allocation")
        q.kubectl("rollout", "status", "deployment/" + NAME, "-n", NAMESPACE, "--timeout=300s", json_output=False)
        q.command(["docker", "run", "--detach", "--name", self.client, "--network", "k3d-" + q.args.name,
                   "--ip", "172.31.240.10", "--cap-drop=ALL", "--cap-add=NET_RAW", "--read-only",
                   "--security-opt=no-new-privileges", "--entrypoint=python3", IMAGE, "-B", "-c",
                   "import signal;signal.pause()"])
        self.stage("1.15.1", "baseline", migrated=False)
        q.kubectl("patch", "ciliumloadbalancerippool", NAME, "--type=json", "-p",
                  json.dumps(migration_patch(self.get_pool())), json_output=False)
        validate_pool(self.get_pool(), self.pool_uid, migrated=True)
        validate_service(self.get_service(), self.service_uid)
        q.install("1.15.19")
        self.stage("1.15.19", "patch-current-minor")
        previous = "1.15.19"
        for version in tuple(CHARTS)[2:]:
            history = json.loads(q.helm("history", "cilium", "-n", "kube-system", "-o", "json"))
            revision = next(x["revision"] for x in history if x["status"] == "deployed")
            q.install(version)
            self.stage(version, "upgrade-" + version)
            q.helm("rollback", "cilium", str(revision), "-n", "kube-system")
            self.stage(previous, "rollback-" + previous)
            q.install(version)
            self.stage(version, "return-" + version)
            previous = version
        if len(self.stages) != 17:
            raise RuntimeError("incomplete L2 transition sequence")
        return {"l2_stages_accepted": True, "stages": self.stages, "production_change": False,
                "physical_network_unqualified": True, "image": IMAGE}


def qualify(qualification):
    fixture = L2Qualification(qualification)
    try:
        return fixture.run()
    finally:
        # The caller's finally owns cluster/VM/images/files; this object owns its external client.
        if qualification.creation_started:
            found = qualification.command(["docker", "ps", "-aq", "--filter", "name=^/" + fixture.client + "$"], private=True).strip()
            if found:
                qualification.command(["docker", "rm", "--force", fixture.client])
