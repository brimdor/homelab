# Status Report - 2026-01-28

- Generated: 2026-01-28 (local time)
- Source: workstation `/homelab-recon` (RECON only)

## Access Validation

### Kubernetes

```text
$ kubectl cluster-info
Kubernetes control plane is running at https://10.0.20.50:6443
CoreDNS is running at https://10.0.20.50:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
Metrics-server is running at https://10.0.20.50:6443/api/v1/namespaces/kube-system/services/https:metrics-server:https/proxy
```

```text
$ kubectl version
Client Version: v1.35.0
Kustomize Version: v5.7.1
Server Version: v1.33.6+k3s1
Warning: version difference between client (1.35) and server (1.33) exceeds the supported minor version skew of +/-1
```

### Controller SSH

```text
$ ssh -o ConnectTimeout=5 brimdor@10.0.20.10 "echo 'Controller accessible'"
Controller accessible
```

### Gitea API

```text
$ ls -la ~/.config/gitea
... .env
```

```text
$ sed -n '1,5p' ~/.config/gitea/.env
# Gitea configuration - please add GITEA_TOKEN
```

Result: Gitea API write access NOT available from workstation (token missing). Read-only repo evidence (issues/PRs) is accessible anonymously; maintenance issue update/create is BLOCKED.

### Gitea Repo Evidence (Unauthenticated Read)

```text
$ curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/pulls?state=open&limit=50" | jq -r '.[] | "#\(.number) | \(.title) | author=\(.user.login) | created=\(.created_at) | mergeable=\(.mergeable)"'
#52 | chore(deps): update docker.io/library/debian docker tag to v13 | author=gitea_admin | created=2026-01-27T15:02:51Z | mergeable=false
#51 | chore(deps): update quay.io/ceph/ceph docker tag to v20 | author=gitea_admin | created=2026-01-25T15:02:27Z | mergeable=true
#50 | chore(deps): update all non-major dependencies | author=gitea_admin | created=2026-01-25T15:02:25Z | mergeable=false
```

```text
$ curl -s "https://git.eaglepass.io/api/v1/repos/ops/homelab/issues?state=open&limit=50" | jq -r '.[] | "#\(.number) | \(.title) | isPR=\(.pull_request!=null) | labels=\((.labels|map(.name)|join(\",\")))"'
#52 | chore(deps): update docker.io/library/debian docker tag to v13 | isPR=true | labels=
#51 | chore(deps): update quay.io/ceph/ceph docker tag to v20 | isPR=true | labels=
#50 | chore(deps): update all non-major dependencies | isPR=true | labels=
#44 | [Maintenance] 2026-01-21 - Homelab | isPR=false | labels=maintenance
#4 | Dependency Dashboard | isPR=false | labels=
```

## Current Blocking Findings

### Apps / ArgoCD: `moltbot` Degraded

```text
$ kubectl -n argocd get applications | grep -v "Synced.*Healthy" || true
moltbot             Synced        Degraded
```

```text
$ kubectl get pods -A --no-headers | grep -E "CrashLoopBackOff|Error|ImagePullBackOff|Pending" || true
moltbot             moltbot-59bcd567d6-gsqzk                                          1/2   ImagePullBackOff   0                35m
```

```text
$ kubectl describe pod -n moltbot moltbot-59bcd567d6-gsqzk | sed -n '1,40p'
...
Image:         10.0.20.11:32309/moltbot:latest
State:          Waiting
  Reason:       ImagePullBackOff
...
Failed to pull image "10.0.20.11:32309/moltbot:latest" ... 10.0.20.11:32309/moltbot:latest: not found
```

```text
$ kubectl -n zot get pods -o wide
zot-0   1/1  Running  ...  IP=10.0.7.144  NODE=bulbasaur

$ kubectl -n zot get svc -o wide
zot  NodePort  10.43.60.181  5000:32309/TCP
```

## Script-Based Recon

### Cluster Recon Script (Opencode)

```text
$ ~/.config/opencode/scripts/recon.sh --json
/home/brimdor/.config/opencode/scripts/recon.sh: line 62: /usr/bin/jq: Argument list too long
```

### Network Check (Opencode)

```json
{
  "timestamp": "2026-01-28T15:57:32-06:00",
  "overall_status": "GREEN",
  "warnings": 0,
  "errors": 0,
  "checks": [
    {"check": "Controller", "status": "GREEN", "message": "ICMP filtered; TCP reachable on port 443", "latency_ms": ""},
    {"check": "NAS", "status": "GREEN", "message": "ICMP filtered; TCP reachable on port 443", "latency_ms": ""},
    {"check": "OPNSense", "status": "GREEN", "message": "ICMP filtered; TCP reachable on port 443", "latency_ms": ""},
    {"check": "VLAN40_STORAGE", "status": "GREEN", "message": "ICMP filtered; TCP reachable on port 443", "latency_ms": ""},
    {"check": "VLAN10_MGMT", "status": "GREEN", "message": "ICMP filtered; TCP reachable on port 443", "latency_ms": ""},
    {"check": "VLAN20_SERVERS", "status": "GREEN", "message": "ICMP filtered; TCP reachable on port 443", "latency_ms": ""},
    {"check": "VLAN30_TRUSTED", "status": "GREEN", "message": "ICMP filtered; TCP reachable on port 443", "latency_ms": ""},
    {"check": "VLAN60_GUEST", "status": "GREEN", "message": "ICMP filtered; TCP reachable on port 443", "latency_ms": ""},
    {"check": "VLAN50_IOT", "status": "GREEN", "message": "ICMP filtered; TCP reachable on port 443", "latency_ms": ""},
    {"check": "INTERNET_1.1.1.1", "status": "GREEN", "message": "OK (8ms, 0% loss)", "latency_ms": "8"},
    {"check": "INTERNET_8.8.8.8", "status": "GREEN", "message": "OK (9ms, 0% loss)", "latency_ms": "9"},
    {"check": "DNS_google.com", "status": "GREEN", "message": "Resolved to 142.251.16.139", "latency_ms": ""},
    {"check": "INTERNET_google.com", "status": "GREEN", "message": "OK (38ms, 0% loss)", "latency_ms": "38"},
    {"check": "OPNSENSE_PORT_443", "status": "GREEN", "message": "Port 443 open", "latency_ms": ""},
    {"check": "OPNSENSE_PORT_22", "status": "GREEN", "message": "Port 22 open", "latency_ms": ""}
  ]
}
```

### NAS / Unraid Check (Opencode)

```json
{
  "timestamp": "2026-01-28T15:56:59-06:00",
  "target": "10.0.40.3",
  "overall_status": "GREEN",
  "warnings": 0,
  "errors": 0,
  "checks": [
    {"check": "NAS_PING", "status": "GREEN", "message": "ICMP filtered; TCP reachable on port 80", "value": "80"},
    {"check": "UNRAID_WEB", "status": "GREEN", "message": "Web interface accessible", "value": ""},
    {"check": "PORT_HTTP", "status": "GREEN", "message": "Port 80 open", "value": ""},
    {"check": "PORT_HTTPS", "status": "GREEN", "message": "Port 443 open", "value": ""},
    {"check": "PORT_SMB", "status": "GREEN", "message": "Port 445 open", "value": ""},
    {"check": "PORT_NFS-RPC", "status": "GREEN", "message": "Port 111 open", "value": ""},
    {"check": "PORT_NFS", "status": "GREEN", "message": "Port 2049 open", "value": ""},
    {"check": "SMB_media", "status": "GREEN", "message": "Share enumeration requires auth (skipped)", "value": ""},
    {"check": "SMB_backups", "status": "GREEN", "message": "Share enumeration requires auth (skipped)", "value": ""},
    {"check": "SMB_appdata", "status": "GREEN", "message": "Share enumeration requires auth (skipped)", "value": ""},
    {"check": "SMB_isos", "status": "GREEN", "message": "Share enumeration requires auth (skipped)", "value": ""},
    {"check": "NFS_media", "status": "GREEN", "message": "Export not configured (skipped)", "value": ""},
    {"check": "NFS_backups", "status": "GREEN", "message": "Export not configured (skipped)", "value": ""}
  ]
}
```

## Baseline Cluster Snapshot

### Nodes + Capacity

```text
$ kubectl get nodes -o wide
NAME         STATUS   ROLES                       AGE    VERSION        INTERNAL-IP   EXTERNAL-IP   OS-IMAGE                        KERNEL-VERSION           CONTAINER-RUNTIME
arcanine     Ready    <none>                      340d   v1.33.6+k3s1   10.0.20.19    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
bulbasaur    Ready    control-plane,etcd,master   340d   v1.33.6+k3s1   10.0.20.13    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
charmander   Ready    control-plane,etcd,master   340d   v1.33.6+k3s1   10.0.20.11    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
chikorita    Ready    <none>                      252d   v1.33.6+k3s1   10.0.20.15    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
cyndaquil    Ready    <none>                      23d    v1.33.6+k3s1   10.0.20.16    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
growlithe    Ready    <none>                      340d   v1.33.6+k3s1   10.0.20.18    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
pikachu      Ready    <none>                      340d   v1.33.6+k3s1   10.0.20.14    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
sprigatito   Ready    <none>                      161d   v1.33.6+k3s1   10.0.20.20    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
squirtle     Ready    control-plane,etcd,master   340d   v1.33.6+k3s1   10.0.20.12    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
totodile     Ready    <none>                      340d   v1.33.6+k3s1   10.0.20.17    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
```

```text
$ kubectl top nodes
NAME         CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)
arcanine     360m         4%       6316Mi          9%
bulbasaur    458m         11%      5192Mi          32%
charmander   680m         17%      5422Mi          22%
chikorita    355m         8%       4755Mi          14%
cyndaquil    390m         9%       4438Mi          27%
growlithe    160m         4%       1422Mi          4%
pikachu      289m         7%       3291Mi          20%
sprigatito   140m         3%       6632Mi          20%
squirtle     607m         15%      5491Mi          34%
totodile     400m         10%      2779Mi          17%
```

### Workload Health (Error Focus)

```text
$ kubectl get pods -A --sort-by=.metadata.namespace
NAMESPACE           NAME                                                              READY   STATUS      RESTARTS        AGE
argocd              argocd-application-controller-0                                   1/1     Running     0               13h
argocd              argocd-applicationset-controller-657d7c7cbc-m9wtv                 1/1     Running     0               13h
argocd              argocd-dex-server-b4d796b55-clqr2                                 1/1     Running     0               13h
argocd              argocd-notifications-controller-76cd8544f4-dm2ml                  1/1     Running     0               13h
argocd              argocd-redis-555d89fb86-l8rqb                                     1/1     Running     0               13h
argocd              argocd-repo-server-664b4b8664-m9rdp                               1/1     Running     0               13h
argocd              argocd-server-78cb8455d4-8c6m8                                    1/1     Running     0               13h
backlog             backlog-844f77c6f6-djzg9                                          3/3     Running     0               13h
backlog-canary      backlog-canary-5f97974969-pmm9m                                   3/3     Running     0               13h
budget              budget-76cf7cb8b6-frjm8                                           2/2     Running     3 (18h ago)     2d13h
budget-canary       budget-canary-75bcc4cf4-mzh9n                                     2/2     Running     0               13h
cert-manager        cert-manager-75d978dc6b-rwr9w                                     1/1     Running     1 (18h ago)     2d13h
cert-manager        cert-manager-cainjector-85dc58857-9w4q4                           1/1     Running     0               13h
cert-manager        cert-manager-webhook-67bd77644b-bsm6q                             1/1     Running     0               13h
clawdbot            clawdbot-5bbfc4b544-7289g                                         2/2     Running     0               13h
cloudflared         cloudflared-589d8d45fd-nk9l8                                      1/1     Running     0               13h
code                weaviate-0                                                        1/1     Running     1 (18h ago)     2d13h
connect             onepassword-connect-5fcbd4c68b-zvnmr                              2/2     Running     2 (18h ago)     2d13h
connect             onepassword-connect-operator-88bfccfd9-mrncx                      1/1     Running     0               13h
default             external-secrets-764b89d78f-xzdfd                                 1/1     Running     1 (18h ago)     5d14h
default             external-secrets-webhook-bcf58f89b-m4c6h                          1/1     Running     1 (18h ago)     2d13h
default             rook-ceph-operator-84f6b7f9fb-6tcg9                               1/1     Running     1 (18h ago)     2d13h
dex                 dex-756c687ddc-v7h55                                              1/1     Running     0               13h
doplarr             doplarr-8647b5dcf9-p4hc5                                          1/1     Running     1 (18h ago)     5d14h
emby                emby-87b7d9cc5-k8zhg                                              1/1     Running     0               18h
explorers-hub       explorers-hub-65d9f459bb-g7sjp                                    1/1     Running     1 (18h ago)     2d13h
explorers-hub       explorers-hub-6c76f6d4d6-d7xcf                                    1/1     Running     0               13h
external-dns        external-dns-6f48c4f67b-9w5jk                                     1/1     Running     3 (13h ago)     2d13h
external-secrets    external-secrets-5c487588d7-tg6tq                                 1/1     Running     1 (18h ago)     2d13h
external-secrets    external-secrets-cert-controller-68c8cf7685-ln8zk                 1/1     Running     0               13h
external-secrets    external-secrets-webhook-848c9fb57f-75hpp                         1/1     Running     1 (18h ago)     2d13h
gitea               gitea-69bdbf685d-kjj8d                                            1/1     Running     1 (18h ago)     5d14h
gitea               gitea-postgresql-0                                                1/1     Running     0               13h
gitea               gitea-valkey-cluster-0                                            1/1     Running     0               13h
gitea               gitea-valkey-cluster-1                                            1/1     Running     0               13h
gitea               gitea-valkey-cluster-2                                            1/1     Running     25 (16h ago)    2d13h
gitea               gitea-valkey-cluster-3                                            1/1     Running     25 (16h ago)    2d13h
gitea               gitea-valkey-cluster-4                                            1/1     Running     1 (18h ago)     5d14h
gitea               gitea-valkey-cluster-5                                            1/1     Running     0               13h
gpu-operator        gpu-feature-discovery-d4n9w                                       1/1     Running     1 (18h ago)     24d
gpu-operator        gpu-feature-discovery-zp7lt                                       1/1     Running     1 (18h ago)     2d3h
gpu-operator        gpu-operator-999cc8dcc-xxknz                                      1/1     Running     9 (18h ago)     5d14h
gpu-operator        gpu-operator-node-feature-discovery-gc-7cc7ccfff8-hvl4m           1/1     Running     0               13h
gpu-operator        gpu-operator-node-feature-discovery-master-d8597d549-v4l8j        1/1     Running     0               13h
gpu-operator        gpu-operator-node-feature-discovery-worker-4vfxp                  1/1     Running     6 (12h ago)     13d
gpu-operator        gpu-operator-node-feature-discovery-worker-89w4g                  1/1     Running     7 (12h ago)     24d
gpu-operator        gpu-operator-node-feature-discovery-worker-8qpdn                  1/1     Running     11 (18h ago)    24d
gpu-operator        gpu-operator-node-feature-discovery-worker-g8fqb                  1/1     Running     13 (12h ago)    24d
gpu-operator        gpu-operator-node-feature-discovery-worker-kzbhr                  1/1     Running     10 (13h ago)    23d
gpu-operator        gpu-operator-node-feature-discovery-worker-qqz5s                  1/1     Running     4 (12h ago)     2d18h
gpu-operator        gpu-operator-node-feature-discovery-worker-rj9td                  1/1     Running     9 (13h ago)     24d
gpu-operator        gpu-operator-node-feature-discovery-worker-vhv8z                  1/1     Running     9 (18h ago)     24d
gpu-operator        gpu-operator-node-feature-discovery-worker-wcnrz                  1/1     Running     11 (18h ago)    24d
gpu-operator        gpu-operator-node-feature-discovery-worker-xls78                  1/1     Running     11 (152m ago)   24d
gpu-operator        nvidia-container-toolkit-daemonset-2vx62                          1/1     Running     1 (18h ago)     2d3h
gpu-operator        nvidia-container-toolkit-daemonset-br9vv                          1/1     Running     1 (18h ago)     24d
gpu-operator        nvidia-cuda-validator-gl6vf                                       0/1     Completed   0               18h
gpu-operator        nvidia-cuda-validator-jqwg5                                       0/1     Completed   0               18h
gpu-operator        nvidia-dcgm-exporter-5trpd                                        1/1     Running     1 (18h ago)     2d3h
gpu-operator        nvidia-dcgm-exporter-7sr6d                                        1/1     Running     1 (18h ago)     24d
gpu-operator        nvidia-device-plugin-daemonset-jc6m7                              1/1     Running     2 (18h ago)     2d3h
gpu-operator        nvidia-device-plugin-daemonset-xhm8t                              1/1     Running     1 (18h ago)     24d
gpu-operator        nvidia-operator-validator-lrq49                                   1/1     Running     1 (18h ago)     2d3h
gpu-operator        nvidia-operator-validator-vj67s                                   1/1     Running     1 (18h ago)     24d
grafana             grafana-569c848d67-cx4l8                                          3/3     Running     0               13h
humbleai            humbleai-75d4f4d646-wfgm4                                         1/1     Running     1 (18h ago)     5d14h
humbleai-canary     humbleai-canary-7fdd77d9cb-jprzg                                  1/1     Running     1 (18h ago)     2d13h
ingress-nginx       ingress-nginx-controller-6f494895f7-t6dmz                         1/1     Running     1 (18h ago)     2d13h
kanidm              kanidm-0                                                          1/1     Running     0               13h
kube-system         cilium-97b27                                                      1/1     Running     4 (18h ago)     29d
kube-system         cilium-bktjp                                                      1/1     Running     1 (18h ago)     29d
kube-system         cilium-c44ng                                                      1/1     Running     12 (13h ago)    29d
kube-system         cilium-h7cmt                                                      1/1     Running     8 (13h ago)     29d
kube-system         cilium-j64nq                                                      1/1     Running     9 (13h ago)     29d
kube-system         cilium-nwzq6                                                      1/1     Running     5 (18h ago)     23d
kube-system         cilium-operator-6999764665-dnh85                                  1/1     Running     20 (18h ago)    26d
kube-system         cilium-r8snc                                                      1/1     Running     7 (18h ago)     29d
kube-system         cilium-rgw2v                                                      1/1     Running     8 (18h ago)     29d
kube-system         cilium-v5gp5                                                      1/1     Running     1 (152m ago)    5h29m
kube-system         cilium-xwhxf                                                      1/1     Running     7 (18h ago)     29d
kube-system         coredns-6d8646cdb8-lj2xr                                          1/1     Running     0               13h
kube-system         hubble-relay-69f5fc5b79-zcbll                                     1/1     Running     0               13h
kube-system         hubble-ui-6548d56557-f9zkq                                        2/2     Running     0               13h
kube-system         kube-vip-bulbasaur                                                1/1     Running     58 (13h ago)    44d
kube-system         kube-vip-charmander                                               1/1     Running     59 (108m ago)   44d
kube-system         kube-vip-squirtle                                                 1/1     Running     58 (9h ago)     44d
kube-system         metrics-server-564cb4ff68-d9t5w                                   1/1     Running     1 (18h ago)     5d14h
kube-system         nfs-client-provisioner-nfs-subdir-external-provisioner-854mxccg   1/1     Running     5 (13h ago)     2d13h
kured               kured-4mx82                                                       1/1     Running     3 (13h ago)     4d6h
kured               kured-fmhx6                                                       1/1     Running     4 (13h ago)     4d6h
kured               kured-m9w56                                                       1/1     Running     3 (18h ago)     4d6h
kured               kured-vrtfq                                                       1/1     Running     3 (18h ago)     4d6h
kured               kured-wmqsk                                                       1/1     Running     4 (152m ago)    4d6h
kured               kured-xmvsm                                                       1/1     Running     3 (13h ago)     4d6h
kured               kured-zwxft                                                       1/1     Running     3 (18h ago)     4d6h
loki                loki-0                                                            1/1     Running     0               13h
loki                loki-promtail-79pqz                                               1/1     Running     21 (152m ago)   50d
loki                loki-promtail-b97xw                                               1/1     Running     19 (18h ago)    50d
loki                loki-promtail-bp6zx                                               1/1     Running     20 (13h ago)    50d
loki                loki-promtail-bsgzf                                               1/1     Running     20 (18h ago)    50d
loki                loki-promtail-gbjnm                                               1/1     Running     19 (18h ago)    50d
loki                loki-promtail-kqwwc                                               1/1     Running     4 (13h ago)     13d
loki                loki-promtail-tf7wq                                               1/1     Running     5 (18h ago)     23d
loki                loki-promtail-xwnbd                                               1/1     Running     24 (13h ago)    50d
monitoring-system   alertmanager-monitoring-system-kube-pro-alertmanager-0            3/3     Running     3 (18h ago)     2d13h
monitoring-system   monitoring-system-kube-pro-operator-6bfb854f6c-5282z              1/1     Running     0               13h
monitoring-system   monitoring-system-kube-state-metrics-99859855-c28mf               1/1     Running     7 (18h ago)     4d6h
monitoring-system   monitoring-system-prometheus-node-exporter-2ff2b                  1/1     Running     3 (13h ago)     14d
monitoring-system   monitoring-system-prometheus-node-exporter-522wf                  1/1     Running     7 (13h ago)     14d
monitoring-system   monitoring-system-prometheus-node-exporter-7phcd                  1/1     Running     3 (18h ago)     2d18h
monitoring-system   monitoring-system-prometheus-node-exporter-86crd                  1/1     Running     3 (18h ago)     14d
monitoring-system   monitoring-system-prometheus-node-exporter-j2h6q                  1/1     Running     4 (13h ago)     13d
monitoring-system   monitoring-system-prometheus-node-exporter-kpfww                  1/1     Running     1 (18h ago)     14d
monitoring-system   monitoring-system-prometheus-node-exporter-pbqhg                  1/1     Running     3 (18h ago)     14d
monitoring-system   monitoring-system-prometheus-node-exporter-pcv7h                  1/1     Running     4 (18h ago)     14d
monitoring-system   monitoring-system-prometheus-node-exporter-x76df                  1/1     Running     3 (18h ago)     14d
monitoring-system   monitoring-system-prometheus-node-exporter-zhs9g                  1/1     Running     6 (152m ago)    14d
monitoring-system   prometheus-monitoring-system-kube-pro-prometheus-0                2/2     Running     0               13h
n8n                 n8n-db-849684747d-5c8wr                                           2/2     Running     3 (18h ago)     5d11h
n8n                 n8n-main-d586c6fcc-hlmkp                                          2/2     Running     0               5h45m
nextcloud           nextcloud-858b6cfdb7-lhhjf                                        2/2     Running     2 (18h ago)     2d13h
ollama              ollama-bc6f4496-bm2pq                                             1/1     Running     1 (18h ago)     44h
ollama              ollama-model-puller-868d6f7557-r2qgk                              1/1     Running     0               13h
openwebui           openwebui-54df8b6fd7-pcgf9                                        1/1     Running     0               13h
postgres            postgres-594559df7b-m8n5t                                         2/2     Running     2 (18h ago)     5d11h
qdrant              qdrant-0                                                          1/1     Running     1 (18h ago)     2d14h
radarr              radarr-f6666f9fc-mfr87                                            1/1     Running     1 (18h ago)     2d14h
renovate            renovate-29493540-9xsm2                                           0/1     Completed   0               6h57m
rook-ceph           ceph-csi-controller-manager-5dc6b7cf95-dd2z9                      1/1     Running     1 (12h ago)     13h
rook-ceph           rook-ceph-conversion-webhook-5b888b9f5d-2gld4                     1/1     Running     0               13h
rook-ceph           rook-ceph-crashcollector-arcanine-7bcd8f5845-4nl4l                0/1     Completed   0               27d
rook-ceph           rook-ceph-crashcollector-arcanine-7bcd8f5845-c5mnf                1/1     Running     2 (18h ago)     2d18h
rook-ceph           rook-ceph-crashcollector-bulbasaur-7874959959-sx95l               1/1     Running     1 (18h ago)     2d13h
rook-ceph           rook-ceph-crashcollector-charmander-78cdcc6cf7-hc857              1/1     Running     1 (18h ago)     2d13h
rook-ceph           rook-ceph-crashcollector-chikorita-67679c895d-6qwc9               1/1     Running     0               5h53m
rook-ceph           rook-ceph-crashcollector-cyndaquil-bf8fbffdb-fqcp9                1/1     Running     1 (18h ago)     2d13h
rook-ceph           rook-ceph-crashcollector-growlithe-6b87f74b6f-dfx7x               1/1     Running     1 (152m ago)    5h6m
rook-ceph           rook-ceph-crashcollector-pikachu-6d8b5d9fdd-h2sbg                 1/1     Running     0               13h
rook-ceph           rook-ceph-crashcollector-sprigatito-6b6667cdd6-dvsfp              1/1     Running     1 (18h ago)     27d
rook-ceph           rook-ceph-crashcollector-totodile-567ff98d67-9k97v                1/1     Running     0               13h
rook-ceph           rook-ceph-exporter-arcanine-66bb9546c5-nrrz4                      1/1     Running     2 (18h ago)     2d18h
rook-ceph           rook-ceph-exporter-bulbasaur-796876b8b9-hnf49                     1/1     Running     1 (18h ago)     2d13h
rook-ceph           rook-ceph-exporter-charmander-f48648b99-vfsjw                     1/1     Running     1 (18h ago)     2d13h
rook-ceph           rook-ceph-exporter-chikorita-84b89d567b-zdlm5                     1/1     Running     0               5h53m
rook-ceph           rook-ceph-exporter-cyndaquil-54667bd65b-dtczf                     1/1     Running     1 (18h ago)     2d13h
rook-ceph           rook-ceph-exporter-growlithe-587f54c495-ztcl2                     1/1     Running     1 (152m ago)    5h6m
rook-ceph           rook-ceph-exporter-pikachu-6585dfcfd6-t4wpp                       1/1     Running     0               13h
rook-ceph           rook-ceph-exporter-sprigatito-59fffcddcb-m4ff4                    1/1     Running     1 (18h ago)     4d6h
rook-ceph           rook-ceph-exporter-totodile-586558887c-nkbh9                      1/1     Running     0               13h
rook-ceph           rook-ceph-mds-standard-rwx-a-77cc678776-zzvhr                     1/1     Running     0               13h
rook-ceph           rook-ceph-mds-standard-rwx-b-5f4ccdb6dd-hlsx5                     1/1     Running     0               13h
rook-ceph           rook-ceph-mgr-a-f868f6448-wlqtb                                   2/2     Running     4 (18h ago)     2d13h
rook-ceph           rook-ceph-mgr-b-76fff94c7d-x4485                                  2/2     Running     2 (18h ago)     2d13h
rook-ceph           rook-ceph-mon-f-69c9dbf44-z7slg                                   1/1     Running     1 (18h ago)     2d13h
rook-ceph           rook-ceph-mon-h-5ddbb587b8-wgzkf                                  1/1     Running     1 (18h ago)     2d13h
rook-ceph           rook-ceph-mon-j-5744596bb9-flhtj                                  1/1     Running     1 (18h ago)     2d13h
rook-ceph           rook-ceph-operator-fd5bd8dff-xcjsq                                1/1     Running     0               13h
rook-ceph           rook-ceph-osd-0-6b6567849-7mzrp                                   1/1     Running     0               5h6m
rook-ceph           rook-ceph-osd-1-57df9d9cc7-swxnr                                  1/1     Running     1 (18h ago)     2d13h
rook-ceph           rook-ceph-osd-2-6649665757-q255w                                  1/1     Running     2 (18h ago)     8d
rook-ceph           rook-ceph-osd-4-db8977f47-nzt9x                                   1/1     Running     1 (18h ago)     2d13h
rook-ceph           rook-ceph-osd-6-75c5f44d8d-zsqhz                                  1/1     Running     1 (152m ago)    5h6m
rook-ceph           rook-ceph-osd-7-748765d5bb-s65nf                                  1/1     Running     1 (18h ago)     27d
rook-ceph           rook-ceph-osd-8-57b698cb4d-wjxw2                                  1/1     Running     3 (18h ago)     27d
rook-ceph           rook-ceph-osd-prepare-arcanine-m2rlj                              0/1     Completed   0               5h7m
rook-ceph           rook-ceph-osd-prepare-bulbasaur-v2rwl                             0/1     Completed   0               5h7m
rook-ceph           rook-ceph-osd-prepare-charmander-8bzk7                            0/1     Completed   0               5h7m
rook-ceph           rook-ceph-osd-prepare-chikorita-q9fxx                             0/1     Completed   0               5h7m
rook-ceph           rook-ceph-osd-prepare-cyndaquil-t2d6f                             0/1     Completed   0               5h7m
rook-ceph           rook-ceph-osd-prepare-growlithe-vmzps                             0/1     Completed   0               5h7m
rook-ceph           rook-ceph-osd-prepare-pikachu-gz6pq                               0/1     Completed   0               5h7m
rook-ceph           rook-ceph-osd-prepare-sprigatito-cxjsk                            0/1     Completed   0               5h7m
rook-ceph           rook-ceph-osd-prepare-squirtle-tnrnq                              0/1     Completed   0               5h7m
rook-ceph           rook-ceph-osd-prepare-totodile-hkb7s                              0/1     Completed   0               5h6m
rook-ceph           rook-ceph-snapshot-controller-7dd476c4f9-978ph                    1/1     Running     1 (12h ago)     13h
rook-ceph           rook-ceph-tools-658fd4db6f-74q5z                                  1/1     Running     0               13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-ctrlplugin-c4dc99579-hgs9w          5/5     Running     5 (18h ago)     2d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-ctrlplugin-c4dc99579-rgxgl          5/5     Running     12 (18h ago)    4d6h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-76n4p                    2/2     Running     12 (13h ago)    4d6h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-8ksjd                    2/2     Running     12 (18h ago)    4d6h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-fkbgp                    2/2     Running     12 (18h ago)    4d6h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-g7lg6                    2/2     Running     0               151m
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-jd8ls                    2/2     Running     12 (18h ago)    4d6h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-kbgmg                    2/2     Running     40 (13h ago)    4d6h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-qd5mh                    2/2     Running     7 (17h ago)     4d6h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-wtkt4                    2/2     Running     20 (18h ago)    4d6h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-xmllg                    2/2     Running     12 (13h ago)    4d6h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-z87qn                    2/2     Running     4 (18h ago)     4d6h
rook-ceph           rook-ceph.rbd.csi.ceph.com-ctrlplugin-5f745fd754-gbkmt            5/5     Running     0               13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-ctrlplugin-5f745fd754-pgc79            5/5     Running     12 (18h ago)    4d6h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-2f4hm                       2/2     Running     4 (18h ago)     4d6h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-8kbsv                       2/2     Running     16 (18h ago)    2d18h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-9tqz8                       2/2     Running     0               151m
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-cg6w5                       2/2     Running     37 (13h ago)    4d6h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-cx6dd                       2/2     Running     12 (13h ago)    4d6h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-frbtp                       2/2     Running     9 (17h ago)     4d6h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-hlqmn                       2/2     Running     12 (13h ago)    4d6h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-qq6d4                       2/2     Running     12 (18h ago)    4d6h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-vpgch                       2/2     Running     12 (18h ago)    4d6h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-x5gzh                       2/2     Running     12 (18h ago)    4d6h
sabnzbd             sabnzbd-854686f555-h7nzf                                          2/2     Running     0               13h
sabnzbd             sabnzbd-f7456ffcd-v5smd                                           2/2     Running     0               13h
searxng             searxng-main-85d6c58b8c-gdjj6                                     1/1     Running     0               13h
searxng             searxng-redis-5b5d46bf8c-vsbzd                                    1/1     Running     1 (18h ago)     5d11h
sonarr              sonarr-6d44cd4845-h2nk2                                           1/1     Running     0               13h
volsync-system      volsync-system-5db49859d-7wp4c                                    2/2     Running     2 (18h ago)     2d13h
weaviate-test       weaviate-0                                                        1/1     Running     0               13h
woodpecker          woodpecker-agent-0                                                1/1     Running     22 (16h ago)    2d13h
woodpecker          woodpecker-server-0                                               1/1     Running     1 (152m ago)    5h17m
zot                 zot-0                                                             1/1     Running     1 (18h ago)     2d13h
```

```text
$ kubectl get pods -A --no-headers | grep -v "Running\|Completed"
(no output)
```

### GitOps Health (ArgoCD)

```text
$ kubectl get applications -n argocd
NAME                SYNC STATUS   HEALTH STATUS
argocd              Synced        Healthy
backlog             Synced        Healthy
backlog-canary      Synced        Healthy
budget              Synced        Healthy
budget-canary       Synced        Healthy
cert-manager        Synced        Healthy
clawdbot            Synced        Healthy
cloudflared         Synced        Healthy
connect             Synced        Healthy
dex                 Synced        Healthy
doplarr             Synced        Healthy
emby                Synced        Healthy
explorers-hub       Synced        Healthy
external-dns        Synced        Healthy
external-secrets    Synced        Healthy
gitea               Synced        Healthy
global-secrets      Synced        Healthy
gpu-operator        Synced        Healthy
grafana             Synced        Healthy
humbleai            Synced        Healthy
humbleai-canary     Synced        Healthy
ingress-nginx       Synced        Healthy
kanidm              Synced        Healthy
kured               Synced        Healthy
loki                Synced        Healthy
monitoring-system   Synced        Healthy
n8n                 Synced        Healthy
nextcloud           Synced        Healthy
ollama              Synced        Healthy
openwebui           Synced        Healthy
postgres            Synced        Healthy
qdrant              Synced        Healthy
radarr              Synced        Healthy
renovate            Synced        Healthy
rook-ceph           Synced        Healthy
sabnzbd             Synced        Healthy
searxng             Synced        Healthy
sonarr              Synced        Healthy
volsync-system      Synced        Healthy
woodpecker          Synced        Healthy
zot                 Synced        Healthy
```

### Recent Events (Last 200)

```text
$ kubectl get events -A --sort-by=.lastTimestamp | tail -200
NAMESPACE   LAST SEEN   TYPE     REASON   OBJECT                              MESSAGE
default     70s         Normal   Valid    clustersecretstore/global-secrets   store validated
```

## System/Core Evidence (kube-system, CNI)

```text
$ kubectl get pods -n kube-system -o wide
NAME                                                              READY   STATUS    RESTARTS        AGE     IP           NODE         NOMINATED NODE   READINESS GATES
cilium-97b27                                                      1/1     Running   4 (18h ago)     29d     10.0.20.19   arcanine     <none>           <none>
cilium-bktjp                                                      1/1     Running   1 (18h ago)     29d     10.0.20.20   sprigatito   <none>           <none>
cilium-c44ng                                                      1/1     Running   12 (13h ago)    29d     10.0.20.14   pikachu      <none>           <none>
cilium-h7cmt                                                      1/1     Running   8 (13h ago)     29d     10.0.20.17   totodile     <none>           <none>
cilium-j64nq                                                      1/1     Running   9 (13h ago)     29d     10.0.20.12   squirtle     <none>           <none>
cilium-nwzq6                                                      1/1     Running   5 (18h ago)     23d     10.0.20.16   cyndaquil    <none>           <none>
cilium-operator-6999764665-dnh85                                  1/1     Running   20 (18h ago)    26d     10.0.20.19   arcanine     <none>           <none>
cilium-r8snc                                                      1/1     Running   7 (18h ago)     29d     10.0.20.13   bulbasaur    <none>           <none>
cilium-rgw2v                                                      1/1     Running   8 (18h ago)     29d     10.0.20.11   charmander   <none>           <none>
cilium-v5gp5                                                      1/1     Running   1 (152m ago)    5h30m   10.0.20.18   growlithe    <none>           <none>
cilium-xwhxf                                                      1/1     Running   7 (18h ago)     29d     10.0.20.15   chikorita    <none>           <none>
coredns-6d8646cdb8-lj2xr                                          1/1     Running   0               13h     10.0.2.105   totodile     <none>           <none>
hubble-relay-69f5fc5b79-zcbll                                     1/1     Running   0               13h     10.0.8.135   pikachu      <none>           <none>
hubble-ui-6548d56557-f9zkq                                        2/2     Running   0               13h     10.0.8.1     pikachu      <none>           <none>
kube-vip-bulbasaur                                                1/1     Running   58 (13h ago)    44d     10.0.20.13   bulbasaur    <none>           <none>
kube-vip-charmander                                               1/1     Running   59 (108m ago)   44d     10.0.20.11   charmander   <none>           <none>
kube-vip-squirtle                                                 1/1     Running   58 (9h ago)     44d     10.0.20.12   squirtle     <none>           <none>
metrics-server-564cb4ff68-d9t5w                                   1/1     Running   1 (18h ago)     5d14h   10.0.0.215   chikorita    <none>           <none>
nfs-client-provisioner-nfs-subdir-external-provisioner-854mxccg   1/1     Running   5 (13h ago)     2d13h   10.0.7.241   bulbasaur    <none>           <none>
```

```text
$ kubectl get pods -n kube-system --no-headers | grep -v "Running\|Completed"
(no output)
```

```text
$ kubectl -n kube-system get ds | grep -i cilium
cilium   10        10        10      10           10          kubernetes.io/os=linux   340d
```

## Ceph Storage Evidence (Rook/Ceph)

```text
$ kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health
HEALTH_OK
```

```text
$ kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph status
  cluster:
    id:     13c20377-d801-43f9-aebd-59f62df5dad1
    health: HEALTH_OK
  services:
    mon: 3 daemons, quorum f,h,j (age 10h)
    mgr: b(active, since 18h), standbys: a
    mds: 1/1 daemons up, 1 hot standby
    osd: 7 osds: 7 up (since 2h), 7 in (since 5h)
  data:
    volumes: 1/1 healthy
    pools:   4 pools, 177 pgs
    objects: 157.03k objects, 608 GiB
    usage:   1.2 TiB used, 2.2 TiB / 3.4 TiB avail
    pgs:     177 active+clean
```

```text
$ kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph df
--- RAW STORAGE ---
CLASS     SIZE    AVAIL     USED  RAW USED  %RAW USED
ssd    3.4 TiB  2.2 TiB  1.2 TiB   1.2 TiB      35.01
TOTAL  3.4 TiB  2.2 TiB  1.2 TiB   1.2 TiB      35.01

--- POOLS ---
POOL                   ID  PGS   STORED  OBJECTS     USED  %USED  MAX AVAIL
standard-rwo            1  128  607 GiB  157.00k  1.2 TiB  39.34    935 GiB
standard-rwx-metadata   2   16   18 MiB       28   37 MiB      0    935 GiB
standard-rwx-data0      3   32      0 B        0      0 B      0    935 GiB
.mgr                    4    1   40 MiB        9  121 MiB      0    624 GiB
```

```text
$ kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph osd tree
ID   CLASS  WEIGHT   TYPE NAME            STATUS  REWEIGHT  PRI-AFF
 -1         3.40022  root default
 -5         1.33429      host arcanine
  2    ssd  0.86850          osd.2            up   1.00000  1.00000
  8    ssd  0.46579          osd.8            up   1.00000  1.00000
 -7         0.40279      host bulbasaur
  4    ssd  0.40279          osd.4            up   1.00000  1.00000
 -3         0.40279      host chikorita
  0    ssd  0.40279          osd.0            up   1.00000  1.00000
 -9         0.40279      host cyndaquil
  1    ssd  0.40279          osd.1            up   1.00000  1.00000
-11         0.45479      host growlithe
  6    ssd  0.45479          osd.6            up   1.00000  1.00000
-13         0.40279      host sprigatito
  7    ssd  0.40279          osd.7            up   1.00000  1.00000
```

```text
$ kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph pg stat
177 pgs: 177 active+clean; 608 GiB data, 1.2 TiB used, 2.2 TiB / 3.4 TiB avail; 1.2 KiB/s rd, 16 KiB/s wr, 4 op/s
```

## Platform Evidence (Ingress, Certs, Secrets, Observability)

```text
$ kubectl get pods -n ingress-nginx -o wide
NAME                                        READY   STATUS    RESTARTS      AGE     IP           NODE         NOMINATED NODE   READINESS GATES
ingress-nginx-controller-6f494895f7-t6dmz   1/1     Running   1 (18h ago)   2d13h   10.0.5.216   charmander   <none>           <none>
```

```text
$ kubectl get svc -n ingress-nginx
NAME                                 TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)                                   AGE
ingress-nginx-controller             LoadBalancer   10.43.151.100   10.0.20.226   80:30242/TCP,443:31665/TCP,22:30840/TCP   44d
ingress-nginx-controller-admission   ClusterIP      10.43.63.5      <none>        443/TCP                                   50d
ingress-nginx-controller-metrics     ClusterIP      10.43.57.130    <none>        10254/TCP                                 50d
```

```text
$ kubectl get ingress -A
NAMESPACE         NAME                CLASS   HOSTS                                        ADDRESS       PORTS     AGE
argocd            argocd-server       nginx   argocd.eaglepass.io                          10.0.20.226   80, 443   50d
backlog-canary    backlog-canary      nginx   backlog-canary.eaglepass.io                  10.0.20.226   80, 443   23d
backlog           backlog             nginx   backlog.eaglepass.io                         10.0.20.226   80, 443   23d
budget-canary     budget-canary       nginx   budget-canary.eaglepass.io                   10.0.20.226   80, 443   29d
budget            budget              nginx   budget.eaglepass.io                          10.0.20.226   80, 443   29d
clawdbot          clawdbot            nginx   clawdbot.eaglepass.io                        10.0.20.226   80, 443   45h
dex               dex                 nginx   dex.eaglepass.io                             10.0.20.226   80, 443   50d
emby              emby                nginx   emby.eaglepass.io,emby-health.eaglepass.io   10.0.20.226   80, 443   50d
explorers-hub     explorers-hub       nginx   explorers.eaglepass.io                       10.0.20.226   80, 443   40d
gitea             gitea               nginx   git.eaglepass.io                             10.0.20.226   80, 443   50d
grafana           grafana             nginx   grafana.eaglepass.io                         10.0.20.226   80, 443   50d
humbleai-canary   humbleai-canary     nginx   humbleai-canary.eaglepass.io                 10.0.20.226   80, 443   50d
humbleai          humbleai            nginx   humbleai.eaglepass.io                        10.0.20.226   80, 443   50d
kanidm            kanidm              nginx   auth.eaglepass.io                            10.0.20.226   80, 443   50d
localai           localai-local-ai    nginx   localai.eaglepass.io                         10.0.20.226   80, 443   50d
n8n               n8n                 nginx   n8n.eaglepass.io                             10.0.20.226   80, 443   28d
nextcloud         nextcloud           nginx   nextcloud.eaglepass.io                       10.0.20.226   80, 443   38d
ollama            ollama              nginx   ollama.eaglepass.io                          10.0.20.226   80, 443   2d3h
openwebui         openwebui           nginx   open.eaglepass.io                            10.0.20.226   80, 443   50d
radarr            radarr              nginx   radarr.eaglepass.io                          10.0.20.226   80, 443   50d
sabnzbd           sabnzbd             nginx   sabnzbd.eaglepass.io                         10.0.20.226   80, 443   50d
searxng           searxng             nginx   searxng.eaglepass.io                         10.0.20.226   80, 443   50d
sonarr            sonarr              nginx   sonarr.eaglepass.io                          10.0.20.226   80, 443   50d
woodpecker        woodpecker-server   nginx   ci.eaglepass.io                              10.0.20.226   80, 443   50d
zot               zot                 nginx   registry.eaglepass.io                        10.0.20.226   80, 443   50d
```

```text
$ kubectl get certificate -A
NAMESPACE         NAME                            READY   SECRET                          AGE
argocd            argocd-server-tls               True    argocd-server-tls               50d
backlog-canary    backlog-companion-canary-tls    True    backlog-companion-canary-tls    23d
backlog           backlog-companion-tls           True    backlog-companion-tls           23d
budget-canary     budget-canary-tls               True    budget-canary-tls               29d
budget            budget-tls                      True    budget-tls                      29d
clawdbot          clawdbot-tls-certificate        True    clawdbot-tls-certificate        45h
dex               dex-tls-certificate             True    dex-tls-certificate             50d
emby              emby-tls-certificate            True    emby-tls-certificate            50d
explorers-hub     explorers-hub-tls-certificate   True    explorers-hub-tls-certificate   40d
gitea             gitea-tls-certificate           True    gitea-tls-certificate           50d
grafana           grafana-general-tls             True    grafana-general-tls             50d
humbleai-canary   humbleai-tls                    True    humbleai-tls                    50d
humbleai          humbleai-tls                    True    humbleai-tls                    50d
kanidm            kanidm-selfsigned               True    kanidm-selfsigned-certificate   50d
kanidm            kanidm-tls-certificate          True    kanidm-tls-certificate          50d
localai           localai-eaglepass-io-tls        True    localai-eaglepass-io-tls        50d
n8n               n8n-tls-certificate             True    n8n-tls-certificate             28d
nextcloud         nextcloud-tls-certificate       True    nextcloud-tls-certificate       38d
ollama            ollama-tls                      True    ollama-tls                      2d3h
openwebui         open-tls-certificate            True    open-tls-certificate            50d
radarr            radarr-tls-certificate          True    radarr-tls-certificate          50d
sabnzbd           sabnzbd-tls-certificate         True    sabnzbd-tls-certificate         50d
searxng           searxng-tls-certificate         True    searxng-tls-certificate         50d
sonarr            sonarr-tls-certificate          True    sonarr-tls-certificate          50d
woodpecker        woodpecker-tls-certificate      True    woodpecker-tls-certificate      50d
zot               zot-tls-certificate             True    zot-tls-certificate             50d
```

```text
$ kubectl get certificaterequest -A
NAMESPACE        NAME                             APPROVED   DENIED   READY   ISSUER              REQUESTER                                         AGE
argocd           argocd-server-tls-1              True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   40d
backlog-canary   backlog-companion-canary-tls-1   True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   23d
budget-canary    budget-canary-tls-1              True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   29d
clawdbot         clawdbot-tls-certificate-1       True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   45h
dex              dex-tls-certificate-1            True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   40d
emby             emby-tls-certificate-1           True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   40d
gitea            gitea-tls-certificate-1          True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   13d
grafana          grafana-general-tls-1            True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   40d
kanidm           kanidm-selfsigned-1              True                True    kanidm-selfsigned   system:serviceaccount:cert-manager:cert-manager   40d
kanidm           kanidm-tls-certificate-1         True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   40d
localai          localai-eaglepass-io-tls-1       True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   26d
n8n              n8n-tls-certificate-1            True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   28d
nextcloud        nextcloud-tls-certificate-1      True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   18d
ollama           ollama-tls-1                     True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   2d3h
openwebui        open-tls-certificate-1           True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   46d
radarr           radarr-tls-certificate-1         True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   40d
sabnzbd          sabnzbd-tls-certificate-1        True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   40d
searxng          searxng-tls-certificate-1        True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   26d
sonarr           sonarr-tls-certificate-1         True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   40d
woodpecker       woodpecker-tls-certificate-1     True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   40d
zot              zot-tls-certificate-1            True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   40d
```

```text
$ kubectl get order -A
NAMESPACE        NAME                                        STATE   AGE
argocd           argocd-server-tls-1-1806234669              valid   40d
backlog-canary   backlog-companion-canary-tls-1-2782044485   valid   23d
budget-canary    budget-canary-tls-1-3397355507              valid   29d
clawdbot         clawdbot-tls-certificate-1-2731418729       valid   45h
dex              dex-tls-certificate-1-1338884972            valid   40d
emby             emby-tls-certificate-1-2214504741           valid   40d
gitea            gitea-tls-certificate-1-1056306335          valid   13d
grafana          grafana-general-tls-1-3286529767            valid   40d
kanidm           kanidm-tls-certificate-1-3684994957         valid   40d
localai          localai-eaglepass-io-tls-1-1636471448       valid   26d
n8n              n8n-tls-certificate-1-1102790071            valid   28d
nextcloud        nextcloud-tls-certificate-1-2289380897      valid   18d
ollama           ollama-tls-1-1173234589                     valid   2d3h
openwebui        open-tls-certificate-1-2903582807           valid   46d
radarr           radarr-tls-certificate-1-727431449          valid   40d
sabnzbd          sabnzbd-tls-certificate-1-2727667487        valid   40d
searxng          searxng-tls-certificate-1-3577027753        valid   26d
sonarr           sonarr-tls-certificate-1-2020712202         valid   40d
woodpecker       woodpecker-tls-certificate-1-3162624335     valid   40d
zot              zot-tls-certificate-1-577498914             valid   40d
```

```text
$ kubectl get challenge -A
No resources found
```

```text
$ kubectl get externalsecret -A
NAMESPACE    NAME                    STORETYPE            STORE            REFRESH INTERVAL   STATUS         READY
connect      op-credentials          ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
dex          dex-secrets             ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
gitea        gitea-admin-secret      ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
grafana      grafana-secrets         ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
renovate     renovate-secret         ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
woodpecker   woodpecker-secret       ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
zot          registry-admin-secret   ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
```

```text
$ kubectl get svc -A
NAMESPACE           NAME                                                 TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)                                   AGE
argocd              argocd-application-controller-metrics                ClusterIP      10.43.150.180   <none>        8082/TCP                                  50d
argocd              argocd-applicationset-controller                     ClusterIP      10.43.209.103   <none>        7000/TCP                                  50d
argocd              argocd-dex-server                                    ClusterIP      10.43.107.60    <none>        5556/TCP,5557/TCP                         50d
argocd              argocd-redis                                         ClusterIP      10.43.117.67    <none>        6379/TCP                                  50d
argocd              argocd-redis-metrics                                 ClusterIP      None            <none>        9121/TCP                                  50d
argocd              argocd-repo-server                                   ClusterIP      10.43.110.4     <none>        8081/TCP                                  50d
argocd              argocd-repo-server-metrics                           ClusterIP      10.43.150.225   <none>        8084/TCP                                  50d
argocd              argocd-server                                        ClusterIP      10.43.208.67    <none>        80/TCP,443/TCP                            50d
argocd              argocd-server-metrics                                ClusterIP      10.43.63.246    <none>        8083/TCP                                  50d
backlog-canary      backlog-canary-backend                               ClusterIP      10.43.232.161   <none>        3000/TCP                                  23d
backlog-canary      backlog-canary-database                              ClusterIP      10.43.205.14    <none>        3306/TCP                                  23d
backlog-canary      backlog-canary-main                                  ClusterIP      10.43.112.80    <none>        80/TCP                                    23d
backlog             backlog-backend                                      ClusterIP      10.43.175.227   <none>        3000/TCP                                  23d
backlog             backlog-database                                     ClusterIP      10.43.201.99    <none>        3306/TCP                                  23d
backlog             backlog-main                                         ClusterIP      10.43.32.104    <none>        80/TCP                                    23d
budget-canary       budget-canary-backend                                ClusterIP      10.43.188.72    <none>        3001/TCP                                  29d
budget-canary       budget-canary-main                                   ClusterIP      10.43.158.233   <none>        80/TCP                                    29d
budget              budget-backend                                       ClusterIP      10.43.140.37    <none>        3001/TCP                                  29d
budget              budget-main                                          ClusterIP      10.43.99.84     <none>        80/TCP                                    29d
cert-manager        cert-manager                                         ClusterIP      10.43.44.128    <none>        9402/TCP                                  50d
cert-manager        cert-manager-cainjector                              ClusterIP      10.43.225.221   <none>        9402/TCP                                  50d
cert-manager        cert-manager-webhook                                 ClusterIP      10.43.221.39    <none>        443/TCP,9402/TCP                          50d
clawdbot            clawdbot                                             ClusterIP      10.43.252.143   <none>        18789/TCP                                 45h
code                weaviate                                             LoadBalancer   10.43.176.74    10.0.20.229   80:31667/TCP                              148d
code                weaviate-grpc                                        LoadBalancer   10.43.88.51     10.0.20.225   50051:31271/TCP                           148d
code                weaviate-headless                                    ClusterIP      None            <none>        80/TCP                                    148d
connect             onepassword-connect                                  NodePort       10.43.223.130   <none>        8081:31195/TCP,8080:32553/TCP             50d
default             external-secrets-webhook                             ClusterIP      10.43.159.20    <none>        443/TCP                                   50d
default             kubernetes                                           ClusterIP      10.43.0.1       <none>        443/TCP                                   340d
dex                 dex                                                  ClusterIP      10.43.203.7     <none>        5556/TCP,5558/TCP                         50d
emby                emby                                                 ClusterIP      10.43.174.205   <none>        8096/TCP,8920/TCP                         50d
explorers-hub       explorers-hub                                        ClusterIP      10.43.120.12    <none>        80/TCP                                    40d
external-dns        external-dns                                         ClusterIP      10.43.117.209   <none>        7979/TCP                                  50d
external-secrets    external-secrets-webhook                             ClusterIP      10.43.199.156   <none>        443/TCP                                   50d
gitea               gitea-http                                           ClusterIP      None            <none>        3000/TCP                                  50d
gitea               gitea-postgresql                                     ClusterIP      10.43.99.56     <none>        5432/TCP                                  50d
gitea               gitea-postgresql-hl                                  ClusterIP      None            <none>        5432/TCP                                  50d
gitea               gitea-ssh                                            ClusterIP      None            <none>        22/TCP                                    50d
gitea               gitea-valkey-cluster                                 ClusterIP      10.43.161.147   <none>        6379/TCP                                  50d
gitea               gitea-valkey-cluster-headless                        ClusterIP      None            <none>        6379/TCP,16379/TCP                        50d
gpu-operator        gpu-operator                                         ClusterIP      10.43.88.89     <none>        8080/TCP                                  50d
gpu-operator        gpu-operator-node-feature-discovery-master           ClusterIP      10.43.125.62    <none>        8080/TCP                                  50d
gpu-operator        nvidia-dcgm-exporter                                 ClusterIP      10.43.174.29    <none>        9400/TCP                                  50d
grafana             grafana                                              ClusterIP      10.43.61.201    <none>        80/TCP                                    50d
humbleai-canary     humbleai-canary-api                                  ClusterIP      10.43.32.147    <none>        3001/TCP                                  50d
humbleai-canary     humbleai-canary-main                                 ClusterIP      10.43.117.11    <none>        3000/TCP                                  50d
humbleai            humbleai-api                                         ClusterIP      10.43.72.221    <none>        3001/TCP                                  50d
humbleai            humbleai-main                                        ClusterIP      10.43.120.8     <none>        3000/TCP                                  50d
ingress-nginx       ingress-nginx-controller                             LoadBalancer   10.43.151.100   10.0.20.226   80:30242/TCP,443:31665/TCP,22:30840/TCP   44d
ingress-nginx       ingress-nginx-controller-admission                   ClusterIP      10.43.63.5      <none>        443/TCP                                   50d
ingress-nginx       ingress-nginx-controller-metrics                     ClusterIP      10.43.57.130    <none>        10254/TCP                                 50d
kanidm              kanidm                                               ClusterIP      10.43.175.231   <none>        443/TCP,636/TCP                           50d
kube-system         hubble-peer                                          ClusterIP      10.43.220.7     <none>        443/TCP                                   340d
kube-system         hubble-relay                                         ClusterIP      10.43.61.204    <none>        80/TCP                                    340d
kube-system         hubble-ui                                            ClusterIP      10.43.116.155   <none>        80/TCP                                    340d
kube-system         kube-dns                                             ClusterIP      10.43.0.10      <none>        53/UDP,53/TCP,9153/TCP                    340d
kube-system         metrics-server                                       ClusterIP      10.43.50.79     <none>        443/TCP                                   340d
kube-system         monitoring-system-kube-pro-coredns                   ClusterIP      None            <none>        9153/TCP                                  14d
kube-system         monitoring-system-kube-pro-kube-controller-manager   ClusterIP      None            <none>        10257/TCP                                 14d
kube-system         monitoring-system-kube-pro-kube-etcd                 ClusterIP      None            <none>        2381/TCP                                  14d
kube-system         monitoring-system-kube-pro-kube-proxy                ClusterIP      None            <none>        10249/TCP                                 14d
kube-system         monitoring-system-kube-pro-kube-scheduler            ClusterIP      None            <none>        10259/TCP                                 14d
kube-system         monitoring-system-kube-pro-kubelet                   ClusterIP      None            <none>        10250/TCP,10255/TCP,4194/TCP              340d
localai             localai-local-ai                                     ClusterIP      10.43.125.61    <none>        8080/TCP                                  50d
loki                loki                                                 ClusterIP      10.43.100.101   <none>        3100/TCP                                  50d
loki                loki-headless                                        ClusterIP      None            <none>        3100/TCP                                  50d
loki                loki-memberlist                                      ClusterIP      None            <none>        7946/TCP                                  50d
monitoring-system   alertmanager-operated                                ClusterIP      None            <none>        9093/TCP,9094/TCP,9094/UDP                14d
monitoring-system   monitoring-system-kube-pro-alertmanager              ClusterIP      10.43.37.243    <none>        9093/TCP,8080/TCP                         14d
monitoring-system   monitoring-system-kube-pro-operator                  ClusterIP      10.43.100.145   <none>        443/TCP                                   14d
monitoring-system   monitoring-system-kube-pro-prometheus                ClusterIP      10.43.248.189   <none>        9090/TCP,8080/TCP                         14d
monitoring-system   monitoring-system-kube-state-metrics                 ClusterIP      10.43.64.9      <none>        8080/TCP                                  14d
monitoring-system   monitoring-system-prometheus-node-exporter           ClusterIP      10.43.249.174   <none>        9100/TCP                                  14d
monitoring-system   prometheus-operated                                  ClusterIP      None            <none>        9090/TCP                                  14d
n8n                 n8n-db                                               ClusterIP      10.43.91.13     <none>        5432/TCP                                  28d
n8n                 n8n-main                                             ClusterIP      10.43.93.45     <none>        5678/TCP                                  27d
nextcloud           nextcloud                                            ClusterIP      10.43.249.172   <none>        443/TCP                                   38d
ollama              ollama                                               ClusterIP      10.43.158.161   <none>        11434/TCP                                 2d3h
openwebui           openwebui                                            ClusterIP      10.43.227.37    <none>        8080/TCP                                  50d
postgres            postgres                                             ClusterIP      10.43.213.83    <none>        5432/TCP                                  38d
qdrant              qdrant                                               ClusterIP      10.43.180.247   <none>        6334/TCP,6333/TCP                         46d
radarr              radarr                                               ClusterIP      10.43.198.87    <none>        7878/TCP                                  50d
rook-ceph           rook-ceph-conversion-webhook                         ClusterIP      10.43.133.154   <none>        443/TCP                                   13d
rook-ceph           rook-ceph-exporter                                   ClusterIP      10.43.48.23     <none>        9926/TCP                                  50d
rook-ceph           rook-ceph-mgr                                        ClusterIP      10.43.148.164   <none>        9283/TCP                                  50d
rook-ceph           rook-ceph-mgr-dashboard                              ClusterIP      10.43.241.96    <none>        7000/TCP                                  50d
rook-ceph           rook-ceph-mon-f                                      ClusterIP      10.43.153.86    <none>        6789/TCP,3300/TCP                         50d
rook-ceph           rook-ceph-mon-h                                      ClusterIP      10.43.243.67    <none>        6789/TCP,3300/TCP                         45d
rook-ceph           rook-ceph-mon-j                                      ClusterIP      10.43.217.162   <none>        6789/TCP,3300/TCP                         16d
sabnzbd             sabnzbd                                              ClusterIP      10.43.94.8      <none>        8080/TCP                                  50d
searxng             searxng                                              ClusterIP      10.43.128.247   <none>        8080/TCP                                  50d
searxng             searxng-main                                         ClusterIP      10.43.181.76    <none>        8080/TCP                                  27d
searxng             searxng-redis                                        ClusterIP      10.43.83.253    <none>        6379/TCP                                  50d
sonarr              sonarr                                               ClusterIP      10.43.237.12    <none>        8989/TCP                                  50d
volsync-system      volsync-system-metrics                               ClusterIP      10.43.163.15    <none>        8443/TCP                                  50d
weaviate-test       weaviate                                             LoadBalancer   10.43.254.79    10.0.20.227   80:32447/TCP                              148d
weaviate-test       weaviate-grpc                                        LoadBalancer   10.43.172.180   10.0.20.228   50051:31738/TCP                           148d
weaviate-test       weaviate-headless                                    ClusterIP      None            <none>        80/TCP                                    148d
woodpecker          woodpecker-server                                    ClusterIP      10.43.172.240   <none>        80/TCP,9000/TCP                           50d
woodpecker          woodpecker-server-headless                           ClusterIP      None            <none>        80/TCP,9000/TCP                           50d
zot                 zot                                                  NodePort       10.43.60.181    <none>        5000:32309/TCP                            50d
```

```text
$ kubectl get clustersecretstore -A
NAME             AGE   STATUS   CAPABILITIES   READY
global-secrets   50d   Valid    ReadWrite      True
```

```text
$ kubectl get pods -n monitoring-system -o wide
NAME                                                     READY   STATUS    RESTARTS       AGE     IP           NODE         NOMINATED NODE   READINESS GATES
alertmanager-monitoring-system-kube-pro-alertmanager-0   3/3     Running   3 (18h ago)    2d13h   10.0.3.162   cyndaquil    <none>           <none>
monitoring-system-kube-pro-operator-6bfb854f6c-5282z     1/1     Running   0              13h     10.0.2.65    totodile     <none>           <none>
monitoring-system-kube-state-metrics-99859855-c28mf      1/1     Running   7 (18h ago)    4d6h    10.0.0.5     chikorita    <none>           <none>
monitoring-system-prometheus-node-exporter-2ff2b         1/1     Running   3 (13h ago)    14d     10.0.20.17   totodile     <none>           <none>
monitoring-system-prometheus-node-exporter-522wf         1/1     Running   7 (13h ago)    14d     10.0.20.14   pikachu      <none>           <none>
monitoring-system-prometheus-node-exporter-7phcd         1/1     Running   3 (18h ago)    2d18h   10.0.20.19   arcanine     <none>           <none>
monitoring-system-prometheus-node-exporter-86crd         1/1     Running   3 (18h ago)    14d     10.0.20.15   chikorita    <none>           <none>
monitoring-system-prometheus-node-exporter-j2h6q         1/1     Running   4 (13h ago)    13d     10.0.20.12   squirtle     <none>           <none>
monitoring-system-prometheus-node-exporter-kpfww         1/1     Running   1 (18h ago)    14d     10.0.20.20   sprigatito   <none>           <none>
monitoring-system-prometheus-node-exporter-pbqhg         1/1     Running   3 (18h ago)    14d     10.0.20.16   cyndaquil    <none>           <none>
monitoring-system-prometheus-node-exporter-pcv7h         1/1     Running   4 (18h ago)    14d     10.0.20.11   charmander   <none>           <none>
monitoring-system-prometheus-node-exporter-x76df         1/1     Running   3 (18h ago)    14d     10.0.20.13   bulbasaur    <none>           <none>
monitoring-system-prometheus-node-exporter-zhs9g         1/1     Running   6 (153m ago)   14d     10.0.20.18   growlithe    <none>           <none>
prometheus-monitoring-system-kube-pro-prometheus-0       2/2     Running   0              13h     10.0.6.79    squirtle     <none>           <none>
```

```text
$ kubectl get pods -n grafana -o wide
NAME                       READY   STATUS    RESTARTS   AGE   IP          NODE        NOMINATED NODE   READINESS GATES
grafana-569c848d67-cx4l8   3/3     Running   0          13h   10.0.0.42   chikorita   <none>           <none>
```

## Repo Evidence (Issues + PRs)

BLOCKED: Missing `GITEA_TOKEN` in `~/.config/gitea/.env` prevents:
- listing open maintenance issue
- capturing open PRs/issues inventory
- creating/updating the single authoritative maintenance issue in Gitea

Expected next step once token is present:

```bash
source ~/.config/gitea/.env
python3 ~/.config/opencode/scripts/homelab-maintenance-issue.py --check-existing
```
