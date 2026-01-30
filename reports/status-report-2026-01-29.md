# Homelab Status Report (2026-01-29)

Generated: 2026-01-29 23:05:54 
Evidence dir: `/tmp/homelab-recon-20260129-230151`

## Evidence Archive

This file captures raw command/script outputs from `/homelab-recon` Phase 1.

## `01_kubectl_cluster-info.txt`

```text
Kubernetes control plane is running at https://10.0.20.50:6443
CoreDNS is running at https://10.0.20.50:6443/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
Metrics-server is running at https://10.0.20.50:6443/api/v1/namespaces/kube-system/services/https:metrics-server:https/proxy

To further debug and diagnose cluster problems, use 'kubectl cluster-info dump'.
```

## `02_kubectl_version.txt`

```text
Client Version: v1.35.0
Kustomize Version: v5.7.1
Server Version: v1.33.6+k3s1
Warning: version difference between client (1.35) and server (1.33) exceeds the supported minor version skew of +/-1
```

## `03_ssh_controller.txt`

```text
Controller accessible
```

## `04_gitea_api_user.txt`

```text
gitea_admin
```

## `05_recon_script.json`

```text
/home/brimdor/.config/opencode/scripts/recon.sh: line 62: /usr/bin/jq: Argument list too long
```

## `05_recon_script.txt`

```text
=== HOMELAB RECON SNAPSHOT [2026-01-30T05:01:54Z] ===

--- Metal Layer (Nodes) ---
NAME         STATUS   ROLES                       AGE    VERSION        INTERNAL-IP   EXTERNAL-IP   OS-IMAGE                        KERNEL-VERSION           CONTAINER-RUNTIME
arcanine     Ready    <none>                      342d   v1.33.6+k3s1   10.0.20.19    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
bulbasaur    Ready    control-plane,etcd,master   342d   v1.33.6+k3s1   10.0.20.13    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
charmander   Ready    control-plane,etcd,master   342d   v1.33.6+k3s1   10.0.20.11    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
chikorita    Ready    <none>                      254d   v1.33.6+k3s1   10.0.20.15    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
cyndaquil    Ready    <none>                      25d    v1.33.6+k3s1   10.0.20.16    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
growlithe    Ready    <none>                      342d   v1.33.6+k3s1   10.0.20.18    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
pikachu      Ready    <none>                      342d   v1.33.6+k3s1   10.0.20.14    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
sprigatito   Ready    <none>                      162d   v1.33.6+k3s1   10.0.20.20    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
squirtle     Ready    control-plane,etcd,master   342d   v1.33.6+k3s1   10.0.20.12    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
totodile     Ready    <none>                      342d   v1.33.6+k3s1   10.0.20.17    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33

--- System Layer (Unhealthy Pods) ---
ALL GREEN

--- Platform Layer (ArgoCD Apps) ---
NAME                SYNC STATUS   HEALTH STATUS

--- Storage Layer (Ceph) ---
  cluster:
    id:     13c20377-d801-43f9-aebd-59f62df5dad1
    health: HEALTH_OK
 
  services:
    mon: 3 daemons, quorum f,h,j (age 5h) [leader: f]
    mgr: b(active, since 5h), standbys: a
    mds: 1/1 daemons up, 1 hot standby
    osd: 7 osds: 7 up (since 5h), 7 in (since 36h)
 
  data:
    volumes: 1/1 healthy
    pools:   4 pools, 177 pgs
    objects: 157.51k objects, 610 GiB
    usage:   1.2 TiB used, 2.2 TiB / 3.4 TiB avail
    pgs:     177 active+clean
 
  io:
    client:   1.1 KiB/s rd, 120 KiB/s wr, 2 op/s rd, 10 op/s wr
```

## `06_network_check.exit`

```text
0
```

## `06_network_check.json`

```text
====================================
  Homelab Network Health Check
====================================

>> Testing Critical Endpoints...

>> Testing Critical Services (TCP)...

>> Testing VLAN Gateways...

>> Testing Internet Connectivity...

====================================
{
  "timestamp": "2026-01-29T23:02:42-06:00",
  "overall_status": "GREEN",
  "warnings": 0,
  "errors": 0,
  "checks": [
    {"check": "Controller", "status": "GREEN", "message": "ICMP blocked (skipped)", "latency_ms": ""}
    ,{"check": "NAS", "status": "GREEN", "message": "ICMP blocked (skipped)", "latency_ms": ""}
    ,{"check": "OPNSense", "status": "GREEN", "message": "ICMP blocked (skipped)", "latency_ms": ""}
    ,{"check": "OPNSENSE_PORT_443", "status": "GREEN", "message": "Port 443 open", "latency_ms": ""}
    ,{"check": "OPNSENSE_PORT_22", "status": "GREEN", "message": "Port 22 open", "latency_ms": ""}
    ,{"check": "CONTROLLER_PORT_22", "status": "GREEN", "message": "Port 22 open", "latency_ms": ""}
    ,{"check": "NAS_PORT_445", "status": "GREEN", "message": "Port 445 open", "latency_ms": ""}
    ,{"check": "VLAN40_STORAGE", "status": "GREEN", "message": "ICMP blocked (skipped)", "latency_ms": ""}
    ,{"check": "VLAN10_MGMT", "status": "GREEN", "message": "ICMP blocked (skipped)", "latency_ms": ""}
    ,{"check": "VLAN20_SERVERS", "status": "GREEN", "message": "ICMP blocked (skipped)", "latency_ms": ""}
    ,{"check": "VLAN30_TRUSTED", "status": "GREEN", "message": "ICMP blocked (skipped)", "latency_ms": ""}
    ,{"check": "VLAN60_GUEST", "status": "GREEN", "message": "ICMP blocked (skipped)", "latency_ms": ""}
    ,{"check": "VLAN50_IOT", "status": "GREEN", "message": "ICMP blocked (skipped)", "latency_ms": ""}
    ,{"check": "INTERNET_1.1.1.1", "status": "GREEN", "message": "OK (8.435ms, 0% loss)", "latency_ms": "8.435"}
    ,{"check": "INTERNET_8.8.8.8", "status": "GREEN", "message": "OK (15.818ms, 0% loss)", "latency_ms": "15.818"}
    ,{"check": "DNS_google.com", "status": "GREEN", "message": "Resolved to 142.250.114.138", "latency_ms": ""}
    ,{"check": "INTERNET_google.com", "status": "GREEN", "message": "OK (9.524ms, 0% loss)", "latency_ms": "9.524"}
  ]
}
```

## `07_nas_check.exit`

```text
0
```

## `07_nas_check.json`

```text
====================================
  Homelab NAS (Unraid) Health Check
====================================

>> Testing NAS Reachability...

>> Testing Web Interface...

>> Testing Network Ports...

>> Testing SMB Shares...

>> Testing NFS Exports...

====================================
{
  "timestamp": "2026-01-29T23:02:47-06:00",
  "target": "10.0.40.3",
  "overall_status": "GREEN",
  "warnings": 0,
  "errors": 0,
  "checks": [
    {"check": "NAS_REACHABLE", "status": "GREEN", "message": "Reachable (tcp/443)", "value": "443"}
    ,{"check": "UNRAID_WEB", "status": "GREEN", "message": "Web interface accessible", "value": ""}
    ,{"check": "PORT_HTTP", "status": "GREEN", "message": "Port 80 open", "value": ""}
    ,{"check": "PORT_HTTPS", "status": "GREEN", "message": "Port 443 open", "value": ""}
    ,{"check": "PORT_SMB", "status": "GREEN", "message": "Port 445 open", "value": ""}
    ,{"check": "PORT_NFS-RPC", "status": "GREEN", "message": "Port 111 open", "value": ""}
    ,{"check": "PORT_NFS", "status": "GREEN", "message": "Port 2049 open", "value": ""}
    ,{"check": "SMB_media", "status": "GREEN", "message": "Share visibility may require auth", "value": ""}
    ,{"check": "SMB_backups", "status": "GREEN", "message": "Share visibility may require auth", "value": ""}
    ,{"check": "SMB_appdata", "status": "GREEN", "message": "Share visibility may require auth", "value": ""}
    ,{"check": "SMB_isos", "status": "GREEN", "message": "Share visibility may require auth", "value": ""}
    ,{"check": "NFS_media", "status": "GREEN", "message": "Export not listed (may be restricted)", "value": ""}
    ,{"check": "NFS_backups", "status": "GREEN", "message": "Export not listed (may be restricted)", "value": ""}
  ]
}
```

## `10_nodes_wide.txt`

```text
NAME         STATUS   ROLES                       AGE    VERSION        INTERNAL-IP   EXTERNAL-IP   OS-IMAGE                        KERNEL-VERSION           CONTAINER-RUNTIME
arcanine     Ready    <none>                      342d   v1.33.6+k3s1   10.0.20.19    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
bulbasaur    Ready    control-plane,etcd,master   342d   v1.33.6+k3s1   10.0.20.13    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
charmander   Ready    control-plane,etcd,master   342d   v1.33.6+k3s1   10.0.20.11    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
chikorita    Ready    <none>                      254d   v1.33.6+k3s1   10.0.20.15    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
cyndaquil    Ready    <none>                      25d    v1.33.6+k3s1   10.0.20.16    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
growlithe    Ready    <none>                      342d   v1.33.6+k3s1   10.0.20.18    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
pikachu      Ready    <none>                      342d   v1.33.6+k3s1   10.0.20.14    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
sprigatito   Ready    <none>                      162d   v1.33.6+k3s1   10.0.20.20    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
squirtle     Ready    control-plane,etcd,master   342d   v1.33.6+k3s1   10.0.20.12    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
totodile     Ready    <none>                      342d   v1.33.6+k3s1   10.0.20.17    <none>        Fedora Linux 39 (Thirty Nine)   6.11.9-100.fc39.x86_64   containerd://2.1.5-k3s1.33
```

## `11_top_nodes.txt`

```text
NAME         CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)   
arcanine     303m         3%       4908Mi          7%          
bulbasaur    515m         12%      5432Mi          34%         
charmander   700m         17%      5038Mi          21%         
chikorita    331m         8%       4642Mi          14%         
cyndaquil    293m         7%       2957Mi          18%         
growlithe    395m         9%       3016Mi          9%          
pikachu      271m         6%       3264Mi          20%         
sprigatito   182m         4%       6405Mi          20%         
squirtle     585m         14%      4647Mi          29%         
totodile     412m         10%      4251Mi          26%
```

## `12_pods_all_sorted.txt`

```text
NAMESPACE           NAME                                                              READY   STATUS      RESTARTS        AGE
argocd              argocd-application-controller-0                                   1/1     Running     0               4h53m
argocd              argocd-applicationset-controller-6596b95bcf-b8k2q                 1/1     Running     0               4h53m
argocd              argocd-dex-server-b4d796b55-clqr2                                 1/1     Running     0               44h
argocd              argocd-notifications-controller-785f4c477d-h48wk                  1/1     Running     0               4h53m
argocd              argocd-redis-55bbfb8dbd-z8mc7                                     1/1     Running     0               4h53m
argocd              argocd-repo-server-7d5954ffb6-qgx9p                               1/1     Running     0               4h53m
argocd              argocd-server-5d9d689778-7d9v7                                    1/1     Running     0               4h53m
backlog             backlog-844f77c6f6-djzg9                                          3/3     Running     0               44h
backlog-canary      backlog-canary-5f97974969-pmm9m                                   3/3     Running     0               44h
budget              budget-76cf7cb8b6-frjm8                                           2/2     Running     3 (2d1h ago)    3d20h
budget-canary       budget-canary-75bcc4cf4-mzh9n                                     2/2     Running     0               44h
cert-manager        cert-manager-75d978dc6b-rwr9w                                     1/1     Running     1 (2d1h ago)    3d20h
cert-manager        cert-manager-cainjector-85dc58857-9w4q4                           1/1     Running     0               44h
cert-manager        cert-manager-webhook-67bd77644b-bsm6q                             1/1     Running     0               44h
cloudflared         cloudflared-5dc6b7849f-ds5kv                                      1/1     Running     0               4h54m
code                weaviate-0                                                        1/1     Running     1 (2d1h ago)    3d20h
connect             onepassword-connect-5fcbd4c68b-zvnmr                              2/2     Running     2 (2d1h ago)    3d20h
connect             onepassword-connect-operator-88bfccfd9-mrncx                      1/1     Running     0               44h
default             external-secrets-764b89d78f-xzdfd                                 1/1     Running     1 (2d1h ago)    6d21h
default             external-secrets-webhook-bcf58f89b-m4c6h                          1/1     Running     1 (2d1h ago)    3d20h
default             rook-ceph-operator-84f6b7f9fb-6tcg9                               1/1     Running     1 (2d1h ago)    3d20h
dex                 dex-756c687ddc-v7h55                                              1/1     Running     0               44h
doplarr             doplarr-8647b5dcf9-p4hc5                                          1/1     Running     1 (2d1h ago)    6d21h
emby                emby-87b7d9cc5-k8zhg                                              1/1     Running     0               2d1h
explorers-hub       explorers-hub-65d9f459bb-g7sjp                                    1/1     Running     1 (2d1h ago)    3d20h
explorers-hub       explorers-hub-6c76f6d4d6-d7xcf                                    1/1     Running     0               44h
external-dns        external-dns-6f48c4f67b-9w5jk                                     1/1     Running     3 (45h ago)     3d20h
external-secrets    external-secrets-cert-controller-7bd8c5b99c-7rbn6                 1/1     Running     0               4h54m
external-secrets    external-secrets-fb66b59cd-tf2kz                                  1/1     Running     0               4h54m
external-secrets    external-secrets-webhook-976ddf7d7-p6l49                          1/1     Running     0               4h54m
gitea               gitea-95955d874-gn87s                                             1/1     Running     0               4h54m
gitea               gitea-postgresql-0                                                1/1     Running     0               44h
gitea               gitea-valkey-cluster-0                                            1/1     Running     0               44h
gitea               gitea-valkey-cluster-1                                            1/1     Running     0               44h
gitea               gitea-valkey-cluster-2                                            1/1     Running     25 (2d ago)     3d20h
gitea               gitea-valkey-cluster-3                                            1/1     Running     25 (47h ago)    3d20h
gitea               gitea-valkey-cluster-4                                            1/1     Running     1 (2d1h ago)    6d21h
gitea               gitea-valkey-cluster-5                                            1/1     Running     0               44h
gpu-operator        gpu-feature-discovery-d4n9w                                       1/1     Running     1 (2d1h ago)    26d
gpu-operator        gpu-feature-discovery-zp7lt                                       1/1     Running     1 (2d1h ago)    3d10h
gpu-operator        gpu-operator-999cc8dcc-xxknz                                      1/1     Running     9 (2d1h ago)    6d21h
gpu-operator        gpu-operator-node-feature-discovery-gc-7cc7ccfff8-hvl4m           1/1     Running     0               44h
gpu-operator        gpu-operator-node-feature-discovery-master-d8597d549-v4l8j        1/1     Running     0               44h
gpu-operator        gpu-operator-node-feature-discovery-worker-4vfxp                  1/1     Running     6 (43h ago)     14d
gpu-operator        gpu-operator-node-feature-discovery-worker-89w4g                  1/1     Running     7 (43h ago)     26d
gpu-operator        gpu-operator-node-feature-discovery-worker-8qpdn                  1/1     Running     11 (2d1h ago)   26d
gpu-operator        gpu-operator-node-feature-discovery-worker-g8fqb                  1/1     Running     13 (43h ago)    26d
gpu-operator        gpu-operator-node-feature-discovery-worker-kzbhr                  1/1     Running     10 (44h ago)    25d
gpu-operator        gpu-operator-node-feature-discovery-worker-qqz5s                  1/1     Running     4 (43h ago)     4d1h
gpu-operator        gpu-operator-node-feature-discovery-worker-rj9td                  1/1     Running     9 (45h ago)     26d
gpu-operator        gpu-operator-node-feature-discovery-worker-vhv8z                  1/1     Running     9 (2d1h ago)    26d
gpu-operator        gpu-operator-node-feature-discovery-worker-wcnrz                  1/1     Running     11 (2d1h ago)   26d
gpu-operator        gpu-operator-node-feature-discovery-worker-xls78                  1/1     Running     11 (33h ago)    26d
gpu-operator        nvidia-container-toolkit-daemonset-2vx62                          1/1     Running     1 (2d1h ago)    3d10h
gpu-operator        nvidia-container-toolkit-daemonset-br9vv                          1/1     Running     1 (2d1h ago)    26d
gpu-operator        nvidia-cuda-validator-gl6vf                                       0/1     Completed   0               2d1h
gpu-operator        nvidia-cuda-validator-jqwg5                                       0/1     Completed   0               2d1h
gpu-operator        nvidia-dcgm-exporter-5trpd                                        1/1     Running     1 (2d1h ago)    3d10h
gpu-operator        nvidia-dcgm-exporter-7sr6d                                        1/1     Running     1 (2d1h ago)    26d
gpu-operator        nvidia-device-plugin-daemonset-jc6m7                              1/1     Running     2 (2d1h ago)    3d10h
gpu-operator        nvidia-device-plugin-daemonset-xhm8t                              1/1     Running     1 (2d1h ago)    26d
gpu-operator        nvidia-operator-validator-lrq49                                   1/1     Running     1 (2d1h ago)    3d10h
gpu-operator        nvidia-operator-validator-vj67s                                   1/1     Running     1 (2d1h ago)    26d
grafana             grafana-84c4f8b575-c8bbx                                          3/3     Running     0               3h49m
humbleai            humbleai-75d4f4d646-wfgm4                                         1/1     Running     1 (2d1h ago)    6d21h
humbleai-canary     humbleai-canary-7fdd77d9cb-jprzg                                  1/1     Running     1 (2d1h ago)    3d20h
ingress-nginx       ingress-nginx-controller-8b668c484-t5bbj                          1/1     Running     0               4h53m
kanidm              kanidm-0                                                          1/1     Running     0               44h
kube-system         cilium-97b27                                                      1/1     Running     4 (2d1h ago)    30d
kube-system         cilium-bktjp                                                      1/1     Running     1 (2d1h ago)    30d
kube-system         cilium-c44ng                                                      1/1     Running     12 (44h ago)    30d
kube-system         cilium-h7cmt                                                      1/1     Running     8 (45h ago)     30d
kube-system         cilium-j64nq                                                      1/1     Running     9 (44h ago)     30d
kube-system         cilium-nwzq6                                                      1/1     Running     5 (2d1h ago)    25d
kube-system         cilium-operator-6999764665-dnh85                                  1/1     Running     20 (2d1h ago)   27d
kube-system         cilium-r8snc                                                      1/1     Running     7 (2d1h ago)    30d
kube-system         cilium-rgw2v                                                      1/1     Running     8 (2d1h ago)    30d
kube-system         cilium-v5gp5                                                      1/1     Running     1 (33h ago)     36h
kube-system         cilium-xwhxf                                                      1/1     Running     7 (2d1h ago)    30d
kube-system         coredns-6d8646cdb8-lj2xr                                          1/1     Running     0               44h
kube-system         hubble-relay-69f5fc5b79-zcbll                                     1/1     Running     0               44h
kube-system         hubble-ui-6548d56557-f9zkq                                        2/2     Running     0               44h
kube-system         kube-vip-bulbasaur                                                1/1     Running     59 (29h ago)    45d
kube-system         kube-vip-charmander                                               1/1     Running     59 (32h ago)    45d
kube-system         kube-vip-squirtle                                                 1/1     Running     59 (163m ago)   45d
kube-system         metrics-server-564cb4ff68-d9t5w                                   1/1     Running     1 (2d1h ago)    6d21h
kube-system         nfs-client-provisioner-nfs-subdir-external-provisioner-854mxccg   1/1     Running     5 (44h ago)     3d20h
kured               kured-4mx82                                                       1/1     Running     3 (44h ago)     5d13h
kured               kured-fmhx6                                                       1/1     Running     4 (44h ago)     5d13h
kured               kured-m9w56                                                       1/1     Running     3 (2d1h ago)    5d13h
kured               kured-vrtfq                                                       1/1     Running     3 (2d1h ago)    5d13h
kured               kured-wmqsk                                                       1/1     Running     4 (33h ago)     5d13h
kured               kured-xmvsm                                                       1/1     Running     3 (45h ago)     5d13h
kured               kured-zwxft                                                       1/1     Running     3 (2d1h ago)    5d13h
loki                loki-0                                                            1/1     Running     0               44h
loki                loki-promtail-79pqz                                               1/1     Running     21 (33h ago)    51d
loki                loki-promtail-b97xw                                               1/1     Running     19 (2d1h ago)   51d
loki                loki-promtail-bp6zx                                               1/1     Running     20 (45h ago)    51d
loki                loki-promtail-bsgzf                                               1/1     Running     20 (2d1h ago)   51d
loki                loki-promtail-gbjnm                                               1/1     Running     19 (2d1h ago)   51d
loki                loki-promtail-kqwwc                                               1/1     Running     4 (44h ago)     14d
loki                loki-promtail-tf7wq                                               1/1     Running     5 (2d1h ago)    25d
loki                loki-promtail-xwnbd                                               1/1     Running     24 (44h ago)    51d
monitoring-system   alertmanager-monitoring-system-kube-pro-alertmanager-0            3/3     Running     0               4h51m
monitoring-system   monitoring-system-kube-pro-operator-7d5594666c-2g7wf              1/1     Running     0               4h53m
monitoring-system   monitoring-system-kube-state-metrics-99859855-c28mf               1/1     Running     7 (2d1h ago)    5d13h
monitoring-system   monitoring-system-prometheus-node-exporter-2ff2b                  1/1     Running     3 (45h ago)     15d
monitoring-system   monitoring-system-prometheus-node-exporter-522wf                  1/1     Running     7 (44h ago)     15d
monitoring-system   monitoring-system-prometheus-node-exporter-7phcd                  1/1     Running     3 (2d1h ago)    4d1h
monitoring-system   monitoring-system-prometheus-node-exporter-86crd                  1/1     Running     3 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-j2h6q                  1/1     Running     4 (44h ago)     14d
monitoring-system   monitoring-system-prometheus-node-exporter-kpfww                  1/1     Running     1 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-pbqhg                  1/1     Running     3 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-pcv7h                  1/1     Running     4 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-x76df                  1/1     Running     3 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-zhs9g                  1/1     Running     6 (33h ago)     15d
monitoring-system   prometheus-monitoring-system-kube-pro-prometheus-0                2/2     Running     0               4h53m
n8n                 n8n-db-849684747d-5c8wr                                           2/2     Running     3 (2d1h ago)    6d18h
n8n                 n8n-main-d586c6fcc-hlmkp                                          2/2     Running     0               36h
nextcloud           nextcloud-858b6cfdb7-lhhjf                                        2/2     Running     2 (2d1h ago)    3d20h
ollama              ollama-6cfccd7ff-lfn87                                            1/1     Running     0               4h54m
ollama              ollama-model-puller-868d6f7557-r2qgk                              1/1     Running     0               44h
openwebui           openwebui-54df8b6fd7-pcgf9                                        1/1     Running     0               44h
postgres            postgres-594559df7b-m8n5t                                         2/2     Running     2 (2d1h ago)    6d18h
qdrant              qdrant-0                                                          1/1     Running     1 (2d1h ago)    3d21h
radarr              radarr-f6666f9fc-mfr87                                            1/1     Running     1 (2d1h ago)    3d21h
renovate            renovate-29493540-9xsm2                                           0/1     Completed   0               38h
renovate            renovate-29494980-r9s99                                           0/1     Completed   0               14h
rook-ceph           ceph-csi-controller-manager-5dc6b7cf95-dd2z9                      1/1     Running     1 (43h ago)     44h
rook-ceph           rook-ceph-conversion-webhook-5b888b9f5d-2gld4                     1/1     Running     0               44h
rook-ceph           rook-ceph-crashcollector-arcanine-5d9d65b756-sbcd9                1/1     Running     0               5h6m
rook-ceph           rook-ceph-crashcollector-arcanine-7bcd8f5845-4nl4l                0/1     Completed   0               29d
rook-ceph           rook-ceph-crashcollector-bulbasaur-5479587f64-lsqlv               1/1     Running     0               5h7m
rook-ceph           rook-ceph-crashcollector-charmander-55579ddc5b-xbfft              1/1     Running     0               5h8m
rook-ceph           rook-ceph-crashcollector-chikorita-659f47b6f7-zlj6z               1/1     Running     0               5h5m
rook-ceph           rook-ceph-crashcollector-cyndaquil-5dbddfb65c-gjfxd               1/1     Running     0               5h8m
rook-ceph           rook-ceph-crashcollector-growlithe-8fccd9bd4-87mf2                1/1     Running     0               5h6m
rook-ceph           rook-ceph-crashcollector-sprigatito-846c5596b7-7w8fv              1/1     Running     0               5h5m
rook-ceph           rook-ceph-exporter-arcanine-5c744855c5-vs9q8                      1/1     Running     0               5h6m
rook-ceph           rook-ceph-exporter-bulbasaur-78bd56d849-kw8nh                     1/1     Running     0               5h7m
rook-ceph           rook-ceph-exporter-charmander-dc9b5dc-jz4v6                       1/1     Running     0               5h8m
rook-ceph           rook-ceph-exporter-chikorita-6479bb6484-789nl                     1/1     Running     0               5h5m
rook-ceph           rook-ceph-exporter-cyndaquil-6597d4d54d-kchqq                     1/1     Running     0               5h8m
rook-ceph           rook-ceph-exporter-growlithe-7ffff74c85-jfb6l                     1/1     Running     0               5h6m
rook-ceph           rook-ceph-exporter-sprigatito-bb57879c6-j8lg7                     1/1     Running     0               5h5m
rook-ceph           rook-ceph-mds-standard-rwx-a-6bd6586df-vlkc2                      1/1     Running     0               5h6m
rook-ceph           rook-ceph-mds-standard-rwx-b-779b85d79c-7tbdh                     1/1     Running     0               5h6m
rook-ceph           rook-ceph-mgr-a-58d8898ccb-qwrml                                  2/2     Running     0               5h6m
rook-ceph           rook-ceph-mgr-b-66cb475bb6-5fbcq                                  2/2     Running     0               5h5m
rook-ceph           rook-ceph-mon-f-5cc966c797-4prh4                                  1/1     Running     0               5h7m
rook-ceph           rook-ceph-mon-h-5ccccdb9bc-qsj9n                                  1/1     Running     0               5h8m
rook-ceph           rook-ceph-mon-j-746c974688-v875x                                  1/1     Running     0               5h8m
rook-ceph           rook-ceph-operator-fd5bd8dff-xcjsq                                1/1     Running     0               44h
rook-ceph           rook-ceph-osd-0-759886b475-c6bpv                                  1/1     Running     0               5h5m
rook-ceph           rook-ceph-osd-1-6d8c5776bc-jxczh                                  1/1     Running     0               5h2m
rook-ceph           rook-ceph-osd-2-65c544f9b9-fgscb                                  1/1     Running     0               5h3m
rook-ceph           rook-ceph-osd-4-68899c7d97-prb47                                  1/1     Running     0               5h4m
rook-ceph           rook-ceph-osd-6-84797665c5-w5vjb                                  1/1     Running     0               5h3m
rook-ceph           rook-ceph-osd-7-7f4d84c6d6-v2qcd                                  1/1     Running     0               5h4m
rook-ceph           rook-ceph-osd-8-5b654b7fd6-qb8xb                                  1/1     Running     0               5h3m
rook-ceph           rook-ceph-osd-prepare-arcanine-qxj8z                              0/1     Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-bulbasaur-xh2cj                             0/1     Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-charmander-hcb4m                            0/1     Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-chikorita-pf6gb                             0/1     Completed   0               4h57m
rook-ceph           rook-ceph-osd-prepare-cyndaquil-8k5vz                             0/1     Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-growlithe-ccwzb                             0/1     Completed   0               4h57m
rook-ceph           rook-ceph-osd-prepare-pikachu-z5qhb                               0/1     Completed   0               4h57m
rook-ceph           rook-ceph-osd-prepare-sprigatito-l6h57                            0/1     Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-squirtle-fdtql                              0/1     Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-totodile-56x6g                              0/1     Completed   0               4h57m
rook-ceph           rook-ceph-snapshot-controller-7dd476c4f9-978ph                    1/1     Running     1 (43h ago)     44h
rook-ceph           rook-ceph-tools-658fd4db6f-74q5z                                  1/1     Running     0               44h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-ctrlplugin-c4dc99579-hgs9w          5/5     Running     5 (2d1h ago)    3d20h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-ctrlplugin-c4dc99579-rgxgl          5/5     Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-76n4p                    2/2     Running     12 (44h ago)    5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-8ksjd                    2/2     Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-fkbgp                    2/2     Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-g7lg6                    2/2     Running     0               33h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-jd8ls                    2/2     Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-kbgmg                    2/2     Running     40 (45h ago)    5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-qd5mh                    2/2     Running     7 (2d ago)      5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-wtkt4                    2/2     Running     20 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-xmllg                    2/2     Running     12 (44h ago)    5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-z87qn                    2/2     Running     4 (2d1h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-ctrlplugin-5f745fd754-gbkmt            5/5     Running     0               44h
rook-ceph           rook-ceph.rbd.csi.ceph.com-ctrlplugin-5f745fd754-pgc79            5/5     Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-2f4hm                       2/2     Running     4 (2d1h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-8kbsv                       2/2     Running     16 (2d1h ago)   4d2h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-9tqz8                       2/2     Running     0               33h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-cg6w5                       2/2     Running     37 (45h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-cx6dd                       2/2     Running     12 (44h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-frbtp                       2/2     Running     9 (2d ago)      5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-hlqmn                       2/2     Running     12 (44h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-qq6d4                       2/2     Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-vpgch                       2/2     Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-x5gzh                       2/2     Running     12 (2d1h ago)   5d13h
sabnzbd             sabnzbd-854686f555-h7nzf                                          2/2     Running     0               44h
sabnzbd             sabnzbd-f7456ffcd-v5smd                                           2/2     Running     0               44h
searxng             searxng-main-85d6c58b8c-gdjj6                                     1/1     Running     0               44h
searxng             searxng-redis-5b5d46bf8c-vsbzd                                    1/1     Running     1 (2d1h ago)    6d18h
sonarr              sonarr-6d44cd4845-h2nk2                                           1/1     Running     0               44h
volsync-system      volsync-system-5db49859d-7wp4c                                    2/2     Running     2 (2d1h ago)    3d20h
weaviate-test       weaviate-0                                                        1/1     Running     0               44h
woodpecker          woodpecker-agent-0                                                1/1     Running     22 (47h ago)    3d20h
woodpecker          woodpecker-server-0                                               1/1     Running     1 (33h ago)     36h
zot                 zot-0                                                             1/1     Running     0               4h54m
```

## `13_pods_all_noheaders.txt`

```text
argocd              argocd-application-controller-0                                   1/1   Running     0               4h53m
argocd              argocd-applicationset-controller-6596b95bcf-b8k2q                 1/1   Running     0               4h53m
argocd              argocd-dex-server-b4d796b55-clqr2                                 1/1   Running     0               44h
argocd              argocd-notifications-controller-785f4c477d-h48wk                  1/1   Running     0               4h53m
argocd              argocd-redis-55bbfb8dbd-z8mc7                                     1/1   Running     0               4h53m
argocd              argocd-repo-server-7d5954ffb6-qgx9p                               1/1   Running     0               4h53m
argocd              argocd-server-5d9d689778-7d9v7                                    1/1   Running     0               4h53m
backlog-canary      backlog-canary-5f97974969-pmm9m                                   3/3   Running     0               44h
backlog             backlog-844f77c6f6-djzg9                                          3/3   Running     0               44h
budget-canary       budget-canary-75bcc4cf4-mzh9n                                     2/2   Running     0               44h
budget              budget-76cf7cb8b6-frjm8                                           2/2   Running     3 (2d1h ago)    3d20h
cert-manager        cert-manager-75d978dc6b-rwr9w                                     1/1   Running     1 (2d1h ago)    3d20h
cert-manager        cert-manager-cainjector-85dc58857-9w4q4                           1/1   Running     0               44h
cert-manager        cert-manager-webhook-67bd77644b-bsm6q                             1/1   Running     0               44h
cloudflared         cloudflared-5dc6b7849f-ds5kv                                      1/1   Running     0               4h54m
code                weaviate-0                                                        1/1   Running     1 (2d1h ago)    3d20h
connect             onepassword-connect-5fcbd4c68b-zvnmr                              2/2   Running     2 (2d1h ago)    3d20h
connect             onepassword-connect-operator-88bfccfd9-mrncx                      1/1   Running     0               44h
default             external-secrets-764b89d78f-xzdfd                                 1/1   Running     1 (2d1h ago)    6d21h
default             external-secrets-webhook-bcf58f89b-m4c6h                          1/1   Running     1 (2d1h ago)    3d20h
default             rook-ceph-operator-84f6b7f9fb-6tcg9                               1/1   Running     1 (2d1h ago)    3d20h
dex                 dex-756c687ddc-v7h55                                              1/1   Running     0               44h
doplarr             doplarr-8647b5dcf9-p4hc5                                          1/1   Running     1 (2d1h ago)    6d21h
emby                emby-87b7d9cc5-k8zhg                                              1/1   Running     0               2d1h
explorers-hub       explorers-hub-65d9f459bb-g7sjp                                    1/1   Running     1 (2d1h ago)    3d20h
explorers-hub       explorers-hub-6c76f6d4d6-d7xcf                                    1/1   Running     0               44h
external-dns        external-dns-6f48c4f67b-9w5jk                                     1/1   Running     3 (45h ago)     3d20h
external-secrets    external-secrets-cert-controller-7bd8c5b99c-7rbn6                 1/1   Running     0               4h54m
external-secrets    external-secrets-fb66b59cd-tf2kz                                  1/1   Running     0               4h54m
external-secrets    external-secrets-webhook-976ddf7d7-p6l49                          1/1   Running     0               4h54m
gitea               gitea-95955d874-gn87s                                             1/1   Running     0               4h54m
gitea               gitea-postgresql-0                                                1/1   Running     0               44h
gitea               gitea-valkey-cluster-0                                            1/1   Running     0               44h
gitea               gitea-valkey-cluster-1                                            1/1   Running     0               44h
gitea               gitea-valkey-cluster-2                                            1/1   Running     25 (2d ago)     3d20h
gitea               gitea-valkey-cluster-3                                            1/1   Running     25 (47h ago)    3d20h
gitea               gitea-valkey-cluster-4                                            1/1   Running     1 (2d1h ago)    6d21h
gitea               gitea-valkey-cluster-5                                            1/1   Running     0               44h
gpu-operator        gpu-feature-discovery-d4n9w                                       1/1   Running     1 (2d1h ago)    26d
gpu-operator        gpu-feature-discovery-zp7lt                                       1/1   Running     1 (2d1h ago)    3d10h
gpu-operator        gpu-operator-999cc8dcc-xxknz                                      1/1   Running     9 (2d1h ago)    6d21h
gpu-operator        gpu-operator-node-feature-discovery-gc-7cc7ccfff8-hvl4m           1/1   Running     0               44h
gpu-operator        gpu-operator-node-feature-discovery-master-d8597d549-v4l8j        1/1   Running     0               44h
gpu-operator        gpu-operator-node-feature-discovery-worker-4vfxp                  1/1   Running     6 (43h ago)     14d
gpu-operator        gpu-operator-node-feature-discovery-worker-89w4g                  1/1   Running     7 (43h ago)     26d
gpu-operator        gpu-operator-node-feature-discovery-worker-8qpdn                  1/1   Running     11 (2d1h ago)   26d
gpu-operator        gpu-operator-node-feature-discovery-worker-g8fqb                  1/1   Running     13 (43h ago)    26d
gpu-operator        gpu-operator-node-feature-discovery-worker-kzbhr                  1/1   Running     10 (44h ago)    25d
gpu-operator        gpu-operator-node-feature-discovery-worker-qqz5s                  1/1   Running     4 (43h ago)     4d1h
gpu-operator        gpu-operator-node-feature-discovery-worker-rj9td                  1/1   Running     9 (45h ago)     26d
gpu-operator        gpu-operator-node-feature-discovery-worker-vhv8z                  1/1   Running     9 (2d1h ago)    26d
gpu-operator        gpu-operator-node-feature-discovery-worker-wcnrz                  1/1   Running     11 (2d1h ago)   26d
gpu-operator        gpu-operator-node-feature-discovery-worker-xls78                  1/1   Running     11 (33h ago)    26d
gpu-operator        nvidia-container-toolkit-daemonset-2vx62                          1/1   Running     1 (2d1h ago)    3d10h
gpu-operator        nvidia-container-toolkit-daemonset-br9vv                          1/1   Running     1 (2d1h ago)    26d
gpu-operator        nvidia-cuda-validator-gl6vf                                       0/1   Completed   0               2d1h
gpu-operator        nvidia-cuda-validator-jqwg5                                       0/1   Completed   0               2d1h
gpu-operator        nvidia-dcgm-exporter-5trpd                                        1/1   Running     1 (2d1h ago)    3d10h
gpu-operator        nvidia-dcgm-exporter-7sr6d                                        1/1   Running     1 (2d1h ago)    26d
gpu-operator        nvidia-device-plugin-daemonset-jc6m7                              1/1   Running     2 (2d1h ago)    3d10h
gpu-operator        nvidia-device-plugin-daemonset-xhm8t                              1/1   Running     1 (2d1h ago)    26d
gpu-operator        nvidia-operator-validator-lrq49                                   1/1   Running     1 (2d1h ago)    3d10h
gpu-operator        nvidia-operator-validator-vj67s                                   1/1   Running     1 (2d1h ago)    26d
grafana             grafana-84c4f8b575-c8bbx                                          3/3   Running     0               3h49m
humbleai-canary     humbleai-canary-7fdd77d9cb-jprzg                                  1/1   Running     1 (2d1h ago)    3d20h
humbleai            humbleai-75d4f4d646-wfgm4                                         1/1   Running     1 (2d1h ago)    6d21h
ingress-nginx       ingress-nginx-controller-8b668c484-t5bbj                          1/1   Running     0               4h54m
kanidm              kanidm-0                                                          1/1   Running     0               44h
kube-system         cilium-97b27                                                      1/1   Running     4 (2d1h ago)    30d
kube-system         cilium-bktjp                                                      1/1   Running     1 (2d1h ago)    30d
kube-system         cilium-c44ng                                                      1/1   Running     12 (44h ago)    30d
kube-system         cilium-h7cmt                                                      1/1   Running     8 (45h ago)     30d
kube-system         cilium-j64nq                                                      1/1   Running     9 (44h ago)     30d
kube-system         cilium-nwzq6                                                      1/1   Running     5 (2d1h ago)    25d
kube-system         cilium-operator-6999764665-dnh85                                  1/1   Running     20 (2d1h ago)   27d
kube-system         cilium-r8snc                                                      1/1   Running     7 (2d1h ago)    30d
kube-system         cilium-rgw2v                                                      1/1   Running     8 (2d1h ago)    30d
kube-system         cilium-v5gp5                                                      1/1   Running     1 (33h ago)     36h
kube-system         cilium-xwhxf                                                      1/1   Running     7 (2d1h ago)    30d
kube-system         coredns-6d8646cdb8-lj2xr                                          1/1   Running     0               44h
kube-system         hubble-relay-69f5fc5b79-zcbll                                     1/1   Running     0               44h
kube-system         hubble-ui-6548d56557-f9zkq                                        2/2   Running     0               44h
kube-system         kube-vip-bulbasaur                                                1/1   Running     59 (29h ago)    45d
kube-system         kube-vip-charmander                                               1/1   Running     59 (32h ago)    45d
kube-system         kube-vip-squirtle                                                 1/1   Running     59 (163m ago)   45d
kube-system         metrics-server-564cb4ff68-d9t5w                                   1/1   Running     1 (2d1h ago)    6d21h
kube-system         nfs-client-provisioner-nfs-subdir-external-provisioner-854mxccg   1/1   Running     5 (44h ago)     3d20h
kured               kured-4mx82                                                       1/1   Running     3 (44h ago)     5d13h
kured               kured-fmhx6                                                       1/1   Running     4 (44h ago)     5d13h
kured               kured-m9w56                                                       1/1   Running     3 (2d1h ago)    5d13h
kured               kured-vrtfq                                                       1/1   Running     3 (2d1h ago)    5d13h
kured               kured-wmqsk                                                       1/1   Running     4 (33h ago)     5d13h
kured               kured-xmvsm                                                       1/1   Running     3 (45h ago)     5d13h
kured               kured-zwxft                                                       1/1   Running     3 (2d1h ago)    5d13h
loki                loki-0                                                            1/1   Running     0               44h
loki                loki-promtail-79pqz                                               1/1   Running     21 (33h ago)    51d
loki                loki-promtail-b97xw                                               1/1   Running     19 (2d1h ago)   51d
loki                loki-promtail-bp6zx                                               1/1   Running     20 (45h ago)    51d
loki                loki-promtail-bsgzf                                               1/1   Running     20 (2d1h ago)   51d
loki                loki-promtail-gbjnm                                               1/1   Running     19 (2d1h ago)   51d
loki                loki-promtail-kqwwc                                               1/1   Running     4 (44h ago)     14d
loki                loki-promtail-tf7wq                                               1/1   Running     5 (2d1h ago)    25d
loki                loki-promtail-xwnbd                                               1/1   Running     24 (44h ago)    51d
monitoring-system   alertmanager-monitoring-system-kube-pro-alertmanager-0            3/3   Running     0               4h51m
monitoring-system   monitoring-system-kube-pro-operator-7d5594666c-2g7wf              1/1   Running     0               4h53m
monitoring-system   monitoring-system-kube-state-metrics-99859855-c28mf               1/1   Running     7 (2d1h ago)    5d13h
monitoring-system   monitoring-system-prometheus-node-exporter-2ff2b                  1/1   Running     3 (45h ago)     15d
monitoring-system   monitoring-system-prometheus-node-exporter-522wf                  1/1   Running     7 (44h ago)     15d
monitoring-system   monitoring-system-prometheus-node-exporter-7phcd                  1/1   Running     3 (2d1h ago)    4d1h
monitoring-system   monitoring-system-prometheus-node-exporter-86crd                  1/1   Running     3 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-j2h6q                  1/1   Running     4 (44h ago)     14d
monitoring-system   monitoring-system-prometheus-node-exporter-kpfww                  1/1   Running     1 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-pbqhg                  1/1   Running     3 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-pcv7h                  1/1   Running     4 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-x76df                  1/1   Running     3 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-zhs9g                  1/1   Running     6 (33h ago)     15d
monitoring-system   prometheus-monitoring-system-kube-pro-prometheus-0                2/2   Running     0               4h53m
n8n                 n8n-db-849684747d-5c8wr                                           2/2   Running     3 (2d1h ago)    6d18h
n8n                 n8n-main-d586c6fcc-hlmkp                                          2/2   Running     0               36h
nextcloud           nextcloud-858b6cfdb7-lhhjf                                        2/2   Running     2 (2d1h ago)    3d20h
ollama              ollama-6cfccd7ff-lfn87                                            1/1   Running     0               4h54m
ollama              ollama-model-puller-868d6f7557-r2qgk                              1/1   Running     0               44h
openwebui           openwebui-54df8b6fd7-pcgf9                                        1/1   Running     0               44h
postgres            postgres-594559df7b-m8n5t                                         2/2   Running     2 (2d1h ago)    6d18h
qdrant              qdrant-0                                                          1/1   Running     1 (2d1h ago)    3d21h
radarr              radarr-f6666f9fc-mfr87                                            1/1   Running     1 (2d1h ago)    3d21h
renovate            renovate-29493540-9xsm2                                           0/1   Completed   0               38h
renovate            renovate-29494980-r9s99                                           0/1   Completed   0               14h
rook-ceph           ceph-csi-controller-manager-5dc6b7cf95-dd2z9                      1/1   Running     1 (43h ago)     44h
rook-ceph           rook-ceph-conversion-webhook-5b888b9f5d-2gld4                     1/1   Running     0               44h
rook-ceph           rook-ceph-crashcollector-arcanine-5d9d65b756-sbcd9                1/1   Running     0               5h6m
rook-ceph           rook-ceph-crashcollector-arcanine-7bcd8f5845-4nl4l                0/1   Completed   0               29d
rook-ceph           rook-ceph-crashcollector-bulbasaur-5479587f64-lsqlv               1/1   Running     0               5h7m
rook-ceph           rook-ceph-crashcollector-charmander-55579ddc5b-xbfft              1/1   Running     0               5h8m
rook-ceph           rook-ceph-crashcollector-chikorita-659f47b6f7-zlj6z               1/1   Running     0               5h5m
rook-ceph           rook-ceph-crashcollector-cyndaquil-5dbddfb65c-gjfxd               1/1   Running     0               5h8m
rook-ceph           rook-ceph-crashcollector-growlithe-8fccd9bd4-87mf2                1/1   Running     0               5h6m
rook-ceph           rook-ceph-crashcollector-sprigatito-846c5596b7-7w8fv              1/1   Running     0               5h5m
rook-ceph           rook-ceph-exporter-arcanine-5c744855c5-vs9q8                      1/1   Running     0               5h6m
rook-ceph           rook-ceph-exporter-bulbasaur-78bd56d849-kw8nh                     1/1   Running     0               5h7m
rook-ceph           rook-ceph-exporter-charmander-dc9b5dc-jz4v6                       1/1   Running     0               5h8m
rook-ceph           rook-ceph-exporter-chikorita-6479bb6484-789nl                     1/1   Running     0               5h5m
rook-ceph           rook-ceph-exporter-cyndaquil-6597d4d54d-kchqq                     1/1   Running     0               5h8m
rook-ceph           rook-ceph-exporter-growlithe-7ffff74c85-jfb6l                     1/1   Running     0               5h6m
rook-ceph           rook-ceph-exporter-sprigatito-bb57879c6-j8lg7                     1/1   Running     0               5h5m
rook-ceph           rook-ceph-mds-standard-rwx-a-6bd6586df-vlkc2                      1/1   Running     0               5h6m
rook-ceph           rook-ceph-mds-standard-rwx-b-779b85d79c-7tbdh                     1/1   Running     0               5h6m
rook-ceph           rook-ceph-mgr-a-58d8898ccb-qwrml                                  2/2   Running     0               5h6m
rook-ceph           rook-ceph-mgr-b-66cb475bb6-5fbcq                                  2/2   Running     0               5h5m
rook-ceph           rook-ceph-mon-f-5cc966c797-4prh4                                  1/1   Running     0               5h7m
rook-ceph           rook-ceph-mon-h-5ccccdb9bc-qsj9n                                  1/1   Running     0               5h8m
rook-ceph           rook-ceph-mon-j-746c974688-v875x                                  1/1   Running     0               5h8m
rook-ceph           rook-ceph-operator-fd5bd8dff-xcjsq                                1/1   Running     0               44h
rook-ceph           rook-ceph-osd-0-759886b475-c6bpv                                  1/1   Running     0               5h5m
rook-ceph           rook-ceph-osd-1-6d8c5776bc-jxczh                                  1/1   Running     0               5h2m
rook-ceph           rook-ceph-osd-2-65c544f9b9-fgscb                                  1/1   Running     0               5h3m
rook-ceph           rook-ceph-osd-4-68899c7d97-prb47                                  1/1   Running     0               5h4m
rook-ceph           rook-ceph-osd-6-84797665c5-w5vjb                                  1/1   Running     0               5h3m
rook-ceph           rook-ceph-osd-7-7f4d84c6d6-v2qcd                                  1/1   Running     0               5h4m
rook-ceph           rook-ceph-osd-8-5b654b7fd6-qb8xb                                  1/1   Running     0               5h3m
rook-ceph           rook-ceph-osd-prepare-arcanine-qxj8z                              0/1   Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-bulbasaur-xh2cj                             0/1   Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-charmander-hcb4m                            0/1   Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-chikorita-pf6gb                             0/1   Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-cyndaquil-8k5vz                             0/1   Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-growlithe-ccwzb                             0/1   Completed   0               4h57m
rook-ceph           rook-ceph-osd-prepare-pikachu-z5qhb                               0/1   Completed   0               4h57m
rook-ceph           rook-ceph-osd-prepare-sprigatito-l6h57                            0/1   Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-squirtle-fdtql                              0/1   Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-totodile-56x6g                              0/1   Completed   0               4h57m
rook-ceph           rook-ceph-snapshot-controller-7dd476c4f9-978ph                    1/1   Running     1 (43h ago)     44h
rook-ceph           rook-ceph-tools-658fd4db6f-74q5z                                  1/1   Running     0               44h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-ctrlplugin-c4dc99579-hgs9w          5/5   Running     5 (2d1h ago)    3d20h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-ctrlplugin-c4dc99579-rgxgl          5/5   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-76n4p                    2/2   Running     12 (44h ago)    5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-8ksjd                    2/2   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-fkbgp                    2/2   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-g7lg6                    2/2   Running     0               33h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-jd8ls                    2/2   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-kbgmg                    2/2   Running     40 (45h ago)    5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-qd5mh                    2/2   Running     7 (2d ago)      5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-wtkt4                    2/2   Running     20 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-xmllg                    2/2   Running     12 (44h ago)    5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-z87qn                    2/2   Running     4 (2d1h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-ctrlplugin-5f745fd754-gbkmt            5/5   Running     0               44h
rook-ceph           rook-ceph.rbd.csi.ceph.com-ctrlplugin-5f745fd754-pgc79            5/5   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-2f4hm                       2/2   Running     4 (2d1h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-8kbsv                       2/2   Running     16 (2d1h ago)   4d2h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-9tqz8                       2/2   Running     0               33h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-cg6w5                       2/2   Running     37 (45h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-cx6dd                       2/2   Running     12 (44h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-frbtp                       2/2   Running     9 (2d ago)      5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-hlqmn                       2/2   Running     12 (44h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-qq6d4                       2/2   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-vpgch                       2/2   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-x5gzh                       2/2   Running     12 (2d1h ago)   5d13h
sabnzbd             sabnzbd-854686f555-h7nzf                                          2/2   Running     0               44h
sabnzbd             sabnzbd-f7456ffcd-v5smd                                           2/2   Running     0               44h
searxng             searxng-main-85d6c58b8c-gdjj6                                     1/1   Running     0               44h
searxng             searxng-redis-5b5d46bf8c-vsbzd                                    1/1   Running     1 (2d1h ago)    6d18h
sonarr              sonarr-6d44cd4845-h2nk2                                           1/1   Running     0               44h
volsync-system      volsync-system-5db49859d-7wp4c                                    2/2   Running     2 (2d1h ago)    3d20h
weaviate-test       weaviate-0                                                        1/1   Running     0               44h
woodpecker          woodpecker-agent-0                                                1/1   Running     22 (47h ago)    3d20h
woodpecker          woodpecker-server-0                                               1/1   Running     1 (33h ago)     36h
zot                 zot-0                                                             1/1   Running     0               4h54m
```

## `14_pods_not_running.txt`

```text

```

## `15_argocd_applications.txt`

```text
NAME                SYNC STATUS   HEALTH STATUS
argocd              Synced        Healthy
backlog             Synced        Healthy
backlog-canary      Synced        Healthy
budget              Synced        Healthy
budget-canary       Synced        Healthy
cert-manager        Synced        Healthy
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

## `16_argocd_applications_not_green.txt`

```text
NAME                SYNC STATUS   HEALTH STATUS
```

## `17_events_all_sorted.txt`

```text
NAMESPACE   LAST SEEN   TYPE     REASON   OBJECT                              MESSAGE
default     3m45s       Normal   Valid    clustersecretstore/global-secrets   store validated
```

## `18_events_last200.txt`

```text
NAMESPACE   LAST SEEN   TYPE     REASON   OBJECT                              MESSAGE
default     3m45s       Normal   Valid    clustersecretstore/global-secrets   store validated
```

## `20_kube-system_pods_wide.txt`

```text
NAME                                                              READY   STATUS    RESTARTS        AGE     IP           NODE         NOMINATED NODE   READINESS GATES
cilium-97b27                                                      1/1     Running   4 (2d1h ago)    30d     10.0.20.19   arcanine     <none>           <none>
cilium-bktjp                                                      1/1     Running   1 (2d1h ago)    30d     10.0.20.20   sprigatito   <none>           <none>
cilium-c44ng                                                      1/1     Running   12 (44h ago)    30d     10.0.20.14   pikachu      <none>           <none>
cilium-h7cmt                                                      1/1     Running   8 (45h ago)     30d     10.0.20.17   totodile     <none>           <none>
cilium-j64nq                                                      1/1     Running   9 (44h ago)     30d     10.0.20.12   squirtle     <none>           <none>
cilium-nwzq6                                                      1/1     Running   5 (2d1h ago)    25d     10.0.20.16   cyndaquil    <none>           <none>
cilium-operator-6999764665-dnh85                                  1/1     Running   20 (2d1h ago)   27d     10.0.20.19   arcanine     <none>           <none>
cilium-r8snc                                                      1/1     Running   7 (2d1h ago)    30d     10.0.20.13   bulbasaur    <none>           <none>
cilium-rgw2v                                                      1/1     Running   8 (2d1h ago)    30d     10.0.20.11   charmander   <none>           <none>
cilium-v5gp5                                                      1/1     Running   1 (33h ago)     36h     10.0.20.18   growlithe    <none>           <none>
cilium-xwhxf                                                      1/1     Running   7 (2d1h ago)    30d     10.0.20.15   chikorita    <none>           <none>
coredns-6d8646cdb8-lj2xr                                          1/1     Running   0               44h     10.0.2.105   totodile     <none>           <none>
hubble-relay-69f5fc5b79-zcbll                                     1/1     Running   0               44h     10.0.8.135   pikachu      <none>           <none>
hubble-ui-6548d56557-f9zkq                                        2/2     Running   0               44h     10.0.8.1     pikachu      <none>           <none>
kube-vip-bulbasaur                                                1/1     Running   59 (29h ago)    45d     10.0.20.13   bulbasaur    <none>           <none>
kube-vip-charmander                                               1/1     Running   59 (32h ago)    45d     10.0.20.11   charmander   <none>           <none>
kube-vip-squirtle                                                 1/1     Running   59 (163m ago)   45d     10.0.20.12   squirtle     <none>           <none>
metrics-server-564cb4ff68-d9t5w                                   1/1     Running   1 (2d1h ago)    6d21h   10.0.0.215   chikorita    <none>           <none>
nfs-client-provisioner-nfs-subdir-external-provisioner-854mxccg   1/1     Running   5 (44h ago)     3d20h   10.0.7.241   bulbasaur    <none>           <none>
```

## `21_kube-system_pods_noheaders.txt`

```text
cilium-97b27                                                      1/1   Running   4 (2d1h ago)    30d
cilium-bktjp                                                      1/1   Running   1 (2d1h ago)    30d
cilium-c44ng                                                      1/1   Running   12 (44h ago)    30d
cilium-h7cmt                                                      1/1   Running   8 (45h ago)     30d
cilium-j64nq                                                      1/1   Running   9 (44h ago)     30d
cilium-nwzq6                                                      1/1   Running   5 (2d1h ago)    25d
cilium-operator-6999764665-dnh85                                  1/1   Running   20 (2d1h ago)   27d
cilium-r8snc                                                      1/1   Running   7 (2d1h ago)    30d
cilium-rgw2v                                                      1/1   Running   8 (2d1h ago)    30d
cilium-v5gp5                                                      1/1   Running   1 (33h ago)     36h
cilium-xwhxf                                                      1/1   Running   7 (2d1h ago)    30d
coredns-6d8646cdb8-lj2xr                                          1/1   Running   0               44h
hubble-relay-69f5fc5b79-zcbll                                     1/1   Running   0               44h
hubble-ui-6548d56557-f9zkq                                        2/2   Running   0               44h
kube-vip-bulbasaur                                                1/1   Running   59 (29h ago)    45d
kube-vip-charmander                                               1/1   Running   59 (32h ago)    45d
kube-vip-squirtle                                                 1/1   Running   59 (163m ago)   45d
metrics-server-564cb4ff68-d9t5w                                   1/1   Running   1 (2d1h ago)    6d21h
nfs-client-provisioner-nfs-subdir-external-provisioner-854mxccg   1/1   Running   5 (44h ago)     3d20h
```

## `22_kube-system_pods_not_running.txt`

```text

```

## `23_kube-system_daemonsets.txt`

```text
NAME     DESIRED   CURRENT   READY   UP-TO-DATE   AVAILABLE   NODE SELECTOR            AGE
cilium   10        10        10      10           10          kubernetes.io/os=linux   342d
```

## `24_cilium_ds.txt`

```text
cilium   10        10        10      10           10          kubernetes.io/os=linux   342d
```

## `25_cilium_pods_wide.txt`

```text
NAME           READY   STATUS    RESTARTS       AGE   IP           NODE         NOMINATED NODE   READINESS GATES
cilium-97b27   1/1     Running   4 (2d1h ago)   30d   10.0.20.19   arcanine     <none>           <none>
cilium-bktjp   1/1     Running   1 (2d1h ago)   30d   10.0.20.20   sprigatito   <none>           <none>
cilium-c44ng   1/1     Running   12 (44h ago)   30d   10.0.20.14   pikachu      <none>           <none>
cilium-h7cmt   1/1     Running   8 (45h ago)    30d   10.0.20.17   totodile     <none>           <none>
cilium-j64nq   1/1     Running   9 (44h ago)    30d   10.0.20.12   squirtle     <none>           <none>
cilium-nwzq6   1/1     Running   5 (2d1h ago)   25d   10.0.20.16   cyndaquil    <none>           <none>
cilium-r8snc   1/1     Running   7 (2d1h ago)   30d   10.0.20.13   bulbasaur    <none>           <none>
cilium-rgw2v   1/1     Running   8 (2d1h ago)   30d   10.0.20.11   charmander   <none>           <none>
cilium-v5gp5   1/1     Running   1 (33h ago)    36h   10.0.20.18   growlithe    <none>           <none>
cilium-xwhxf   1/1     Running   7 (2d1h ago)   30d   10.0.20.15   chikorita    <none>           <none>
```

## `30_rook-ceph_pods_wide.txt`

```text
NAME                                                       READY   STATUS      RESTARTS        AGE     IP           NODE         NOMINATED NODE   READINESS GATES
ceph-csi-controller-manager-5dc6b7cf95-dd2z9               1/1     Running     1 (43h ago)     44h     10.0.6.89    squirtle     <none>           <none>
rook-ceph-conversion-webhook-5b888b9f5d-2gld4              1/1     Running     0               44h     10.0.2.142   totodile     <none>           <none>
rook-ceph-crashcollector-arcanine-5d9d65b756-sbcd9         1/1     Running     0               5h6m    10.0.4.235   arcanine     <none>           <none>
rook-ceph-crashcollector-arcanine-7bcd8f5845-4nl4l         0/1     Completed   0               29d     <none>       arcanine     <none>           <none>
rook-ceph-crashcollector-bulbasaur-5479587f64-lsqlv        1/1     Running     0               5h8m    10.0.7.117   bulbasaur    <none>           <none>
rook-ceph-crashcollector-charmander-55579ddc5b-xbfft       1/1     Running     0               5h9m    10.0.5.221   charmander   <none>           <none>
rook-ceph-crashcollector-chikorita-659f47b6f7-zlj6z        1/1     Running     0               5h5m    10.0.0.198   chikorita    <none>           <none>
rook-ceph-crashcollector-cyndaquil-5dbddfb65c-gjfxd        1/1     Running     0               5h8m    10.0.3.157   cyndaquil    <none>           <none>
rook-ceph-crashcollector-growlithe-8fccd9bd4-87mf2         1/1     Running     0               5h7m    10.0.1.238   growlithe    <none>           <none>
rook-ceph-crashcollector-sprigatito-846c5596b7-7w8fv       1/1     Running     0               5h5m    10.0.9.166   sprigatito   <none>           <none>
rook-ceph-exporter-arcanine-5c744855c5-vs9q8               1/1     Running     0               5h6m    10.0.4.142   arcanine     <none>           <none>
rook-ceph-exporter-bulbasaur-78bd56d849-kw8nh              1/1     Running     0               5h8m    10.0.7.27    bulbasaur    <none>           <none>
rook-ceph-exporter-charmander-dc9b5dc-jz4v6                1/1     Running     0               5h9m    10.0.5.86    charmander   <none>           <none>
rook-ceph-exporter-chikorita-6479bb6484-789nl              1/1     Running     0               5h5m    10.0.0.55    chikorita    <none>           <none>
rook-ceph-exporter-cyndaquil-6597d4d54d-kchqq              1/1     Running     0               5h8m    10.0.3.139   cyndaquil    <none>           <none>
rook-ceph-exporter-growlithe-7ffff74c85-jfb6l              1/1     Running     0               5h7m    10.0.1.53    growlithe    <none>           <none>
rook-ceph-exporter-sprigatito-bb57879c6-j8lg7              1/1     Running     0               5h5m    10.0.9.161   sprigatito   <none>           <none>
rook-ceph-mds-standard-rwx-a-6bd6586df-vlkc2               1/1     Running     0               5h7m    10.0.1.93    growlithe    <none>           <none>
rook-ceph-mds-standard-rwx-b-779b85d79c-7tbdh              1/1     Running     0               5h6m    10.0.1.109   growlithe    <none>           <none>
rook-ceph-mgr-a-58d8898ccb-qwrml                           2/2     Running     0               5h6m    10.0.1.221   growlithe    <none>           <none>
rook-ceph-mgr-b-66cb475bb6-5fbcq                           2/2     Running     0               5h6m    10.0.7.20    bulbasaur    <none>           <none>
rook-ceph-mon-f-5cc966c797-4prh4                           1/1     Running     0               5h8m    10.0.7.87    bulbasaur    <none>           <none>
rook-ceph-mon-h-5ccccdb9bc-qsj9n                           1/1     Running     0               5h9m    10.0.5.39    charmander   <none>           <none>
rook-ceph-mon-j-746c974688-v875x                           1/1     Running     0               5h8m    10.0.3.239   cyndaquil    <none>           <none>
rook-ceph-operator-fd5bd8dff-xcjsq                         1/1     Running     0               44h     10.0.2.114   totodile     <none>           <none>
rook-ceph-osd-0-759886b475-c6bpv                           1/1     Running     0               5h5m    10.0.0.134   chikorita    <none>           <none>
rook-ceph-osd-1-6d8c5776bc-jxczh                           1/1     Running     0               5h2m    10.0.3.63    cyndaquil    <none>           <none>
rook-ceph-osd-2-65c544f9b9-fgscb                           1/1     Running     0               5h3m    10.0.4.12    arcanine     <none>           <none>
rook-ceph-osd-4-68899c7d97-prb47                           1/1     Running     0               5h4m    10.0.7.35    bulbasaur    <none>           <none>
rook-ceph-osd-6-84797665c5-w5vjb                           1/1     Running     0               5h3m    10.0.1.200   growlithe    <none>           <none>
rook-ceph-osd-7-7f4d84c6d6-v2qcd                           1/1     Running     0               5h4m    10.0.9.206   sprigatito   <none>           <none>
rook-ceph-osd-8-5b654b7fd6-qb8xb                           1/1     Running     0               5h3m    10.0.4.195   arcanine     <none>           <none>
rook-ceph-osd-prepare-arcanine-qxj8z                       0/1     Completed   0               4h58m   10.0.4.105   arcanine     <none>           <none>
rook-ceph-osd-prepare-bulbasaur-xh2cj                      0/1     Completed   0               4h58m   10.0.7.187   bulbasaur    <none>           <none>
rook-ceph-osd-prepare-charmander-hcb4m                     0/1     Completed   0               4h58m   10.0.5.224   charmander   <none>           <none>
rook-ceph-osd-prepare-chikorita-pf6gb                      0/1     Completed   0               4h58m   10.0.0.36    chikorita    <none>           <none>
rook-ceph-osd-prepare-cyndaquil-8k5vz                      0/1     Completed   0               4h58m   10.0.3.88    cyndaquil    <none>           <none>
rook-ceph-osd-prepare-growlithe-ccwzb                      0/1     Completed   0               4h58m   10.0.1.56    growlithe    <none>           <none>
rook-ceph-osd-prepare-pikachu-z5qhb                        0/1     Completed   0               4h58m   10.0.8.90    pikachu      <none>           <none>
rook-ceph-osd-prepare-sprigatito-l6h57                     0/1     Completed   0               4h58m   10.0.9.158   sprigatito   <none>           <none>
rook-ceph-osd-prepare-squirtle-fdtql                       0/1     Completed   0               4h58m   10.0.6.120   squirtle     <none>           <none>
rook-ceph-osd-prepare-totodile-56x6g                       0/1     Completed   0               4h58m   10.0.2.53    totodile     <none>           <none>
rook-ceph-snapshot-controller-7dd476c4f9-978ph             1/1     Running     1 (43h ago)     44h     10.0.6.76    squirtle     <none>           <none>
rook-ceph-tools-658fd4db6f-74q5z                           1/1     Running     0               44h     10.0.2.26    totodile     <none>           <none>
rook-ceph.cephfs.csi.ceph.com-ctrlplugin-c4dc99579-hgs9w   5/5     Running     5 (2d1h ago)    3d20h   10.0.5.32    charmander   <none>           <none>
rook-ceph.cephfs.csi.ceph.com-ctrlplugin-c4dc99579-rgxgl   5/5     Running     12 (2d1h ago)   5d13h   10.0.4.113   arcanine     <none>           <none>
rook-ceph.cephfs.csi.ceph.com-nodeplugin-76n4p             2/2     Running     12 (44h ago)    5d13h   10.0.20.14   pikachu      <none>           <none>
rook-ceph.cephfs.csi.ceph.com-nodeplugin-8ksjd             2/2     Running     12 (2d1h ago)   5d13h   10.0.20.11   charmander   <none>           <none>
rook-ceph.cephfs.csi.ceph.com-nodeplugin-fkbgp             2/2     Running     12 (2d1h ago)   5d13h   10.0.20.16   cyndaquil    <none>           <none>
rook-ceph.cephfs.csi.ceph.com-nodeplugin-g7lg6             2/2     Running     0               33h     10.0.20.18   growlithe    <none>           <none>
rook-ceph.cephfs.csi.ceph.com-nodeplugin-jd8ls             2/2     Running     12 (2d1h ago)   5d13h   10.0.20.13   bulbasaur    <none>           <none>
rook-ceph.cephfs.csi.ceph.com-nodeplugin-kbgmg             2/2     Running     40 (45h ago)    5d13h   10.0.20.17   totodile     <none>           <none>
rook-ceph.cephfs.csi.ceph.com-nodeplugin-qd5mh             2/2     Running     7 (2d ago)      5d13h   10.0.20.15   chikorita    <none>           <none>
rook-ceph.cephfs.csi.ceph.com-nodeplugin-wtkt4             2/2     Running     20 (2d1h ago)   5d13h   10.0.20.19   arcanine     <none>           <none>
rook-ceph.cephfs.csi.ceph.com-nodeplugin-xmllg             2/2     Running     12 (44h ago)    5d13h   10.0.20.12   squirtle     <none>           <none>
rook-ceph.cephfs.csi.ceph.com-nodeplugin-z87qn             2/2     Running     4 (2d1h ago)    5d13h   10.0.20.20   sprigatito   <none>           <none>
rook-ceph.rbd.csi.ceph.com-ctrlplugin-5f745fd754-gbkmt     5/5     Running     0               44h     10.0.2.239   totodile     <none>           <none>
rook-ceph.rbd.csi.ceph.com-ctrlplugin-5f745fd754-pgc79     5/5     Running     12 (2d1h ago)   5d13h   10.0.4.107   arcanine     <none>           <none>
rook-ceph.rbd.csi.ceph.com-nodeplugin-2f4hm                2/2     Running     4 (2d1h ago)    5d13h   10.0.20.20   sprigatito   <none>           <none>
rook-ceph.rbd.csi.ceph.com-nodeplugin-8kbsv                2/2     Running     16 (2d1h ago)   4d2h    10.0.20.19   arcanine     <none>           <none>
rook-ceph.rbd.csi.ceph.com-nodeplugin-9tqz8                2/2     Running     0               33h     10.0.20.18   growlithe    <none>           <none>
rook-ceph.rbd.csi.ceph.com-nodeplugin-cg6w5                2/2     Running     37 (45h ago)    5d13h   10.0.20.17   totodile     <none>           <none>
rook-ceph.rbd.csi.ceph.com-nodeplugin-cx6dd                2/2     Running     12 (44h ago)    5d13h   10.0.20.14   pikachu      <none>           <none>
rook-ceph.rbd.csi.ceph.com-nodeplugin-frbtp                2/2     Running     9 (2d ago)      5d13h   10.0.20.15   chikorita    <none>           <none>
rook-ceph.rbd.csi.ceph.com-nodeplugin-hlqmn                2/2     Running     12 (44h ago)    5d13h   10.0.20.12   squirtle     <none>           <none>
rook-ceph.rbd.csi.ceph.com-nodeplugin-qq6d4                2/2     Running     12 (2d1h ago)   5d13h   10.0.20.11   charmander   <none>           <none>
rook-ceph.rbd.csi.ceph.com-nodeplugin-vpgch                2/2     Running     12 (2d1h ago)   5d13h   10.0.20.13   bulbasaur    <none>           <none>
rook-ceph.rbd.csi.ceph.com-nodeplugin-x5gzh                2/2     Running     12 (2d1h ago)   5d13h   10.0.20.16   cyndaquil    <none>           <none>
```

## `31_ceph_health.txt`

```text
HEALTH_OK
```

## `32_ceph_status.txt`

```text
  cluster:
    id:     13c20377-d801-43f9-aebd-59f62df5dad1
    health: HEALTH_OK
 
  services:
    mon: 3 daemons, quorum f,h,j (age 5h) [leader: f]
    mgr: b(active, since 5h), standbys: a
    mds: 1/1 daemons up, 1 hot standby
    osd: 7 osds: 7 up (since 5h), 7 in (since 36h)
 
  data:
    volumes: 1/1 healthy
    pools:   4 pools, 177 pgs
    objects: 157.51k objects, 610 GiB
    usage:   1.2 TiB used, 2.2 TiB / 3.4 TiB avail
    pgs:     177 active+clean
 
  io:
    client:   1.2 KiB/s rd, 64 KiB/s wr, 2 op/s rd, 5 op/s wr
```

## `33_ceph_health_detail.txt`

```text
HEALTH_OK
```

## `34_ceph_df.txt`

```text
--- RAW STORAGE ---
CLASS     SIZE    AVAIL     USED  RAW USED  %RAW USED
ssd    3.4 TiB  2.2 TiB  1.2 TiB   1.2 TiB      35.08
TOTAL  3.4 TiB  2.2 TiB  1.2 TiB   1.2 TiB      35.08
 
--- POOLS ---
POOL                   ID  PGS   STORED  OBJECTS     USED  %USED  MAX AVAIL
standard-rwo            1  128  609 GiB  157.47k  1.2 TiB  39.51    932 GiB
standard-rwx-metadata   2   16   19 MiB       28   37 MiB      0    932 GiB
standard-rwx-data0      3   32      0 B        0      0 B      0    932 GiB
.mgr                    4    1   31 MiB        9   92 MiB      0    621 GiB
```

## `35_ceph_osd_tree.txt`

```text
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

## `36_ceph_pg_stat.txt`

```text
177 pgs: 177 active+clean; 610 GiB data, 1.2 TiB used, 2.2 TiB / 3.4 TiB avail; 1.8 KiB/s rd, 62 KiB/s wr, 8 op/s
```

## `40_ingress_nginx_pods_wide.txt`

```text
NAME                                       READY   STATUS    RESTARTS   AGE     IP           NODE        NOMINATED NODE   READINESS GATES
ingress-nginx-controller-8b668c484-t5bbj   1/1     Running   0          4h54m   10.0.7.161   bulbasaur   <none>           <none>
```

## `41_ingress_nginx_services.txt`

```text
NAME                                 TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)                                   AGE
ingress-nginx-controller             LoadBalancer   10.43.151.100   10.0.20.226   80:30242/TCP,443:31665/TCP,22:30840/TCP   45d
ingress-nginx-controller-admission   ClusterIP      10.43.63.5      <none>        443/TCP                                   52d
ingress-nginx-controller-metrics     ClusterIP      10.43.57.130    <none>        10254/TCP                                 52d
```

## `42_ingress_all.txt`

```text
NAMESPACE         NAME                CLASS   HOSTS                                        ADDRESS       PORTS     AGE
argocd            argocd-server       nginx   argocd.eaglepass.io                          10.0.20.226   80, 443   52d
backlog-canary    backlog-canary      nginx   backlog-canary.eaglepass.io                  10.0.20.226   80, 443   25d
backlog           backlog             nginx   backlog.eaglepass.io                         10.0.20.226   80, 443   25d
budget-canary     budget-canary       nginx   budget-canary.eaglepass.io                   10.0.20.226   80, 443   31d
budget            budget              nginx   budget.eaglepass.io                          10.0.20.226   80, 443   30d
dex               dex                 nginx   dex.eaglepass.io                             10.0.20.226   80, 443   52d
emby              emby                nginx   emby.eaglepass.io,emby-health.eaglepass.io   10.0.20.226   80, 443   52d
explorers-hub     explorers-hub       nginx   explorers.eaglepass.io                       10.0.20.226   80, 443   41d
gitea             gitea               nginx   git.eaglepass.io                             10.0.20.226   80, 443   52d
grafana           grafana             nginx   grafana.eaglepass.io                         10.0.20.226   80, 443   52d
humbleai-canary   humbleai-canary     nginx   humbleai-canary.eaglepass.io                 10.0.20.226   80, 443   52d
humbleai          humbleai            nginx   humbleai.eaglepass.io                        10.0.20.226   80, 443   52d
kanidm            kanidm              nginx   auth.eaglepass.io                            10.0.20.226   80, 443   52d
localai           localai-local-ai    nginx   localai.eaglepass.io                         10.0.20.226   80, 443   52d
n8n               n8n                 nginx   n8n.eaglepass.io                             10.0.20.226   80, 443   29d
nextcloud         nextcloud           nginx   nextcloud.eaglepass.io                       10.0.20.226   80, 443   39d
ollama            ollama              nginx   ollama.eaglepass.io                          10.0.20.226   80, 443   3d10h
openwebui         openwebui           nginx   open.eaglepass.io                            10.0.20.226   80, 443   52d
radarr            radarr              nginx   radarr.eaglepass.io                          10.0.20.226   80, 443   52d
sabnzbd           sabnzbd             nginx   sabnzbd.eaglepass.io                         10.0.20.226   80, 443   52d
searxng           searxng             nginx   searxng.eaglepass.io                         10.0.20.226   80, 443   52d
sonarr            sonarr              nginx   sonarr.eaglepass.io                          10.0.20.226   80, 443   52d
woodpecker        woodpecker-server   nginx   ci.eaglepass.io                              10.0.20.226   80, 443   52d
zot               zot                 nginx   registry.eaglepass.io                        10.0.20.226   80, 443   52d
```

## `43_certificates_all.txt`

```text
NAMESPACE         NAME                            READY   SECRET                          AGE
argocd            argocd-server-tls               True    argocd-server-tls               52d
backlog-canary    backlog-companion-canary-tls    True    backlog-companion-canary-tls    25d
backlog           backlog-companion-tls           True    backlog-companion-tls           25d
budget-canary     budget-canary-tls               True    budget-canary-tls               31d
budget            budget-tls                      True    budget-tls                      30d
dex               dex-tls-certificate             True    dex-tls-certificate             52d
emby              emby-tls-certificate            True    emby-tls-certificate            52d
explorers-hub     explorers-hub-tls-certificate   True    explorers-hub-tls-certificate   41d
gitea             gitea-tls-certificate           True    gitea-tls-certificate           52d
grafana           grafana-general-tls             True    grafana-general-tls             52d
humbleai-canary   humbleai-tls                    True    humbleai-tls                    52d
humbleai          humbleai-tls                    True    humbleai-tls                    52d
kanidm            kanidm-selfsigned               True    kanidm-selfsigned-certificate   52d
kanidm            kanidm-tls-certificate          True    kanidm-tls-certificate          52d
localai           localai-eaglepass-io-tls        True    localai-eaglepass-io-tls        52d
n8n               n8n-tls-certificate             True    n8n-tls-certificate             29d
nextcloud         nextcloud-tls-certificate       True    nextcloud-tls-certificate       39d
ollama            ollama-tls                      True    ollama-tls                      3d10h
openwebui         open-tls-certificate            True    open-tls-certificate            52d
radarr            radarr-tls-certificate          True    radarr-tls-certificate          52d
sabnzbd           sabnzbd-tls-certificate         True    sabnzbd-tls-certificate         52d
searxng           searxng-tls-certificate         True    searxng-tls-certificate         52d
sonarr            sonarr-tls-certificate          True    sonarr-tls-certificate          52d
woodpecker        woodpecker-tls-certificate      True    woodpecker-tls-certificate      52d
zot               zot-tls-certificate             True    zot-tls-certificate             52d
```

## `44_certificaterequests_all.txt`

```text
NAMESPACE        NAME                             APPROVED   DENIED   READY   ISSUER              REQUESTER                                         AGE
argocd           argocd-server-tls-1              True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
backlog-canary   backlog-companion-canary-tls-1   True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   25d
budget-canary    budget-canary-tls-1              True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   31d
dex              dex-tls-certificate-1            True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
emby             emby-tls-certificate-1           True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
gitea            gitea-tls-certificate-1          True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   14d
grafana          grafana-general-tls-1            True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
humbleai         humbleai-tls-1                   True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   22h
kanidm           kanidm-selfsigned-1              True                True    kanidm-selfsigned   system:serviceaccount:cert-manager:cert-manager   41d
kanidm           kanidm-tls-certificate-1         True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
localai          localai-eaglepass-io-tls-1       True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   27d
n8n              n8n-tls-certificate-1            True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   29d
nextcloud        nextcloud-tls-certificate-1      True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   20d
ollama           ollama-tls-1                     True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   3d10h
openwebui        open-tls-certificate-1           True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   48d
radarr           radarr-tls-certificate-1         True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
sabnzbd          sabnzbd-tls-certificate-1        True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
searxng          searxng-tls-certificate-1        True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   27d
sonarr           sonarr-tls-certificate-1         True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
woodpecker       woodpecker-tls-certificate-1     True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
zot              zot-tls-certificate-1            True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
```

## `44_certificaterequests_last200.txt`

```text
NAMESPACE        NAME                             APPROVED   DENIED   READY   ISSUER              REQUESTER                                         AGE
argocd           argocd-server-tls-1              True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
backlog-canary   backlog-companion-canary-tls-1   True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   25d
budget-canary    budget-canary-tls-1              True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   31d
dex              dex-tls-certificate-1            True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
emby             emby-tls-certificate-1           True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
gitea            gitea-tls-certificate-1          True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   14d
grafana          grafana-general-tls-1            True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
humbleai         humbleai-tls-1                   True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   22h
kanidm           kanidm-selfsigned-1              True                True    kanidm-selfsigned   system:serviceaccount:cert-manager:cert-manager   41d
kanidm           kanidm-tls-certificate-1         True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
localai          localai-eaglepass-io-tls-1       True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   27d
n8n              n8n-tls-certificate-1            True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   29d
nextcloud        nextcloud-tls-certificate-1      True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   20d
ollama           ollama-tls-1                     True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   3d10h
openwebui        open-tls-certificate-1           True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   48d
radarr           radarr-tls-certificate-1         True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
sabnzbd          sabnzbd-tls-certificate-1        True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
searxng          searxng-tls-certificate-1        True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   27d
sonarr           sonarr-tls-certificate-1         True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
woodpecker       woodpecker-tls-certificate-1     True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
zot              zot-tls-certificate-1            True                True    letsencrypt-prod    system:serviceaccount:cert-manager:cert-manager   42d
```

## `45_orders_all.txt`

```text
NAMESPACE        NAME                                        STATE   AGE
argocd           argocd-server-tls-1-1806234669              valid   42d
backlog-canary   backlog-companion-canary-tls-1-2782044485   valid   25d
budget-canary    budget-canary-tls-1-3397355507              valid   31d
dex              dex-tls-certificate-1-1338884972            valid   42d
emby             emby-tls-certificate-1-2214504741           valid   42d
gitea            gitea-tls-certificate-1-1056306335          valid   14d
grafana          grafana-general-tls-1-3286529767            valid   42d
humbleai         humbleai-tls-1-448166436                    valid   22h
kanidm           kanidm-tls-certificate-1-3684994957         valid   42d
localai          localai-eaglepass-io-tls-1-1636471448       valid   27d
n8n              n8n-tls-certificate-1-1102790071            valid   29d
nextcloud        nextcloud-tls-certificate-1-2289380897      valid   20d
ollama           ollama-tls-1-1173234589                     valid   3d10h
openwebui        open-tls-certificate-1-2903582807           valid   48d
radarr           radarr-tls-certificate-1-727431449          valid   42d
sabnzbd          sabnzbd-tls-certificate-1-2727667487        valid   42d
searxng          searxng-tls-certificate-1-3577027753        valid   27d
sonarr           sonarr-tls-certificate-1-2020712202         valid   42d
woodpecker       woodpecker-tls-certificate-1-3162624335     valid   42d
zot              zot-tls-certificate-1-577498914             valid   42d
```

## `45_orders_last200.txt`

```text
NAMESPACE        NAME                                        STATE   AGE
argocd           argocd-server-tls-1-1806234669              valid   42d
backlog-canary   backlog-companion-canary-tls-1-2782044485   valid   25d
budget-canary    budget-canary-tls-1-3397355507              valid   31d
dex              dex-tls-certificate-1-1338884972            valid   42d
emby             emby-tls-certificate-1-2214504741           valid   42d
gitea            gitea-tls-certificate-1-1056306335          valid   14d
grafana          grafana-general-tls-1-3286529767            valid   42d
humbleai         humbleai-tls-1-448166436                    valid   22h
kanidm           kanidm-tls-certificate-1-3684994957         valid   42d
localai          localai-eaglepass-io-tls-1-1636471448       valid   27d
n8n              n8n-tls-certificate-1-1102790071            valid   29d
nextcloud        nextcloud-tls-certificate-1-2289380897      valid   20d
ollama           ollama-tls-1-1173234589                     valid   3d10h
openwebui        open-tls-certificate-1-2903582807           valid   48d
radarr           radarr-tls-certificate-1-727431449          valid   42d
sabnzbd          sabnzbd-tls-certificate-1-2727667487        valid   42d
searxng          searxng-tls-certificate-1-3577027753        valid   27d
sonarr           sonarr-tls-certificate-1-2020712202         valid   42d
woodpecker       woodpecker-tls-certificate-1-3162624335     valid   42d
zot              zot-tls-certificate-1-577498914             valid   42d
```

## `46_challenges_all.txt`

```text
No resources found
```

## `46_challenges_last200.txt`

```text
No resources found
```

## `47_externalsecrets_all.txt`

```text
NAMESPACE    NAME                    STORETYPE            STORE            REFRESH INTERVAL   STATUS         READY
connect      op-credentials          ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
dex          dex-secrets             ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
gitea        gitea-admin-secret      ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
grafana      grafana-secrets         ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
renovate     renovate-secret         ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
woodpecker   woodpecker-secret       ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
zot          registry-admin-secret   ClusterSecretStore   global-secrets   1h0m0s             SecretSynced   True
```

## `48_secretstores_all.txt`

```text
No resources found
```

## `49_clustersecretstores_all.txt`

```text
NAME             AGE   STATUS   CAPABILITIES   READY
global-secrets   52d   Valid    ReadWrite      True
```

## `50_monitoring-system_pods_wide.txt`

```text
NAME                                                     READY   STATUS    RESTARTS       AGE     IP           NODE         NOMINATED NODE   READINESS GATES
alertmanager-monitoring-system-kube-pro-alertmanager-0   3/3     Running   0              4h52m   10.0.8.143   pikachu      <none>           <none>
monitoring-system-kube-pro-operator-7d5594666c-2g7wf     1/1     Running   0              4h54m   10.0.7.100   bulbasaur    <none>           <none>
monitoring-system-kube-state-metrics-99859855-c28mf      1/1     Running   7 (2d1h ago)   5d13h   10.0.0.5     chikorita    <none>           <none>
monitoring-system-prometheus-node-exporter-2ff2b         1/1     Running   3 (45h ago)    15d     10.0.20.17   totodile     <none>           <none>
monitoring-system-prometheus-node-exporter-522wf         1/1     Running   7 (44h ago)    15d     10.0.20.14   pikachu      <none>           <none>
monitoring-system-prometheus-node-exporter-7phcd         1/1     Running   3 (2d1h ago)   4d1h    10.0.20.19   arcanine     <none>           <none>
monitoring-system-prometheus-node-exporter-86crd         1/1     Running   3 (2d1h ago)   15d     10.0.20.15   chikorita    <none>           <none>
monitoring-system-prometheus-node-exporter-j2h6q         1/1     Running   4 (44h ago)    14d     10.0.20.12   squirtle     <none>           <none>
monitoring-system-prometheus-node-exporter-kpfww         1/1     Running   1 (2d1h ago)   15d     10.0.20.20   sprigatito   <none>           <none>
monitoring-system-prometheus-node-exporter-pbqhg         1/1     Running   3 (2d1h ago)   15d     10.0.20.16   cyndaquil    <none>           <none>
monitoring-system-prometheus-node-exporter-pcv7h         1/1     Running   4 (2d1h ago)   15d     10.0.20.11   charmander   <none>           <none>
monitoring-system-prometheus-node-exporter-x76df         1/1     Running   3 (2d1h ago)   15d     10.0.20.13   bulbasaur    <none>           <none>
monitoring-system-prometheus-node-exporter-zhs9g         1/1     Running   6 (33h ago)    15d     10.0.20.18   growlithe    <none>           <none>
prometheus-monitoring-system-kube-pro-prometheus-0       2/2     Running   0              4h54m   10.0.2.181   totodile     <none>           <none>
```

## `51_grafana_pods_wide.txt`

```text
NAME                       READY   STATUS    RESTARTS   AGE     IP           NODE        NOMINATED NODE   READINESS GATES
grafana-84c4f8b575-c8bbx   3/3     Running   0          3h50m   10.0.1.108   growlithe   <none>           <none>
```

## `59_pods_all_noheaders_again.txt`

```text
argocd              argocd-application-controller-0                                   1/1   Running     0               4h54m
argocd              argocd-applicationset-controller-6596b95bcf-b8k2q                 1/1   Running     0               4h54m
argocd              argocd-dex-server-b4d796b55-clqr2                                 1/1   Running     0               44h
argocd              argocd-notifications-controller-785f4c477d-h48wk                  1/1   Running     0               4h54m
argocd              argocd-redis-55bbfb8dbd-z8mc7                                     1/1   Running     0               4h54m
argocd              argocd-repo-server-7d5954ffb6-qgx9p                               1/1   Running     0               4h54m
argocd              argocd-server-5d9d689778-7d9v7                                    1/1   Running     0               4h54m
backlog-canary      backlog-canary-5f97974969-pmm9m                                   3/3   Running     0               44h
backlog             backlog-844f77c6f6-djzg9                                          3/3   Running     0               44h
budget-canary       budget-canary-75bcc4cf4-mzh9n                                     2/2   Running     0               44h
budget              budget-76cf7cb8b6-frjm8                                           2/2   Running     3 (2d1h ago)    3d20h
cert-manager        cert-manager-75d978dc6b-rwr9w                                     1/1   Running     1 (2d1h ago)    3d20h
cert-manager        cert-manager-cainjector-85dc58857-9w4q4                           1/1   Running     0               44h
cert-manager        cert-manager-webhook-67bd77644b-bsm6q                             1/1   Running     0               44h
cloudflared         cloudflared-5dc6b7849f-ds5kv                                      1/1   Running     0               4h55m
code                weaviate-0                                                        1/1   Running     1 (2d1h ago)    3d20h
connect             onepassword-connect-5fcbd4c68b-zvnmr                              2/2   Running     2 (2d1h ago)    3d20h
connect             onepassword-connect-operator-88bfccfd9-mrncx                      1/1   Running     0               44h
default             external-secrets-764b89d78f-xzdfd                                 1/1   Running     1 (2d1h ago)    6d21h
default             external-secrets-webhook-bcf58f89b-m4c6h                          1/1   Running     1 (2d1h ago)    3d20h
default             rook-ceph-operator-84f6b7f9fb-6tcg9                               1/1   Running     1 (2d1h ago)    3d20h
dex                 dex-756c687ddc-v7h55                                              1/1   Running     0               44h
doplarr             doplarr-8647b5dcf9-p4hc5                                          1/1   Running     1 (2d1h ago)    6d21h
emby                emby-87b7d9cc5-k8zhg                                              1/1   Running     0               2d1h
explorers-hub       explorers-hub-65d9f459bb-g7sjp                                    1/1   Running     1 (2d1h ago)    3d20h
explorers-hub       explorers-hub-6c76f6d4d6-d7xcf                                    1/1   Running     0               44h
external-dns        external-dns-6f48c4f67b-9w5jk                                     1/1   Running     3 (45h ago)     3d20h
external-secrets    external-secrets-cert-controller-7bd8c5b99c-7rbn6                 1/1   Running     0               4h54m
external-secrets    external-secrets-fb66b59cd-tf2kz                                  1/1   Running     0               4h54m
external-secrets    external-secrets-webhook-976ddf7d7-p6l49                          1/1   Running     0               4h54m
gitea               gitea-95955d874-gn87s                                             1/1   Running     0               4h55m
gitea               gitea-postgresql-0                                                1/1   Running     0               44h
gitea               gitea-valkey-cluster-0                                            1/1   Running     0               45h
gitea               gitea-valkey-cluster-1                                            1/1   Running     0               44h
gitea               gitea-valkey-cluster-2                                            1/1   Running     25 (2d ago)     3d20h
gitea               gitea-valkey-cluster-3                                            1/1   Running     25 (47h ago)    3d20h
gitea               gitea-valkey-cluster-4                                            1/1   Running     1 (2d1h ago)    6d21h
gitea               gitea-valkey-cluster-5                                            1/1   Running     0               44h
gpu-operator        gpu-feature-discovery-d4n9w                                       1/1   Running     1 (2d1h ago)    26d
gpu-operator        gpu-feature-discovery-zp7lt                                       1/1   Running     1 (2d1h ago)    3d10h
gpu-operator        gpu-operator-999cc8dcc-xxknz                                      1/1   Running     9 (2d1h ago)    6d21h
gpu-operator        gpu-operator-node-feature-discovery-gc-7cc7ccfff8-hvl4m           1/1   Running     0               44h
gpu-operator        gpu-operator-node-feature-discovery-master-d8597d549-v4l8j        1/1   Running     0               44h
gpu-operator        gpu-operator-node-feature-discovery-worker-4vfxp                  1/1   Running     6 (43h ago)     14d
gpu-operator        gpu-operator-node-feature-discovery-worker-89w4g                  1/1   Running     7 (43h ago)     26d
gpu-operator        gpu-operator-node-feature-discovery-worker-8qpdn                  1/1   Running     11 (2d1h ago)   26d
gpu-operator        gpu-operator-node-feature-discovery-worker-g8fqb                  1/1   Running     13 (43h ago)    26d
gpu-operator        gpu-operator-node-feature-discovery-worker-kzbhr                  1/1   Running     10 (44h ago)    25d
gpu-operator        gpu-operator-node-feature-discovery-worker-qqz5s                  1/1   Running     4 (43h ago)     4d1h
gpu-operator        gpu-operator-node-feature-discovery-worker-rj9td                  1/1   Running     9 (45h ago)     26d
gpu-operator        gpu-operator-node-feature-discovery-worker-vhv8z                  1/1   Running     9 (2d1h ago)    26d
gpu-operator        gpu-operator-node-feature-discovery-worker-wcnrz                  1/1   Running     11 (2d1h ago)   26d
gpu-operator        gpu-operator-node-feature-discovery-worker-xls78                  1/1   Running     11 (33h ago)    26d
gpu-operator        nvidia-container-toolkit-daemonset-2vx62                          1/1   Running     1 (2d1h ago)    3d10h
gpu-operator        nvidia-container-toolkit-daemonset-br9vv                          1/1   Running     1 (2d1h ago)    26d
gpu-operator        nvidia-cuda-validator-gl6vf                                       0/1   Completed   0               2d1h
gpu-operator        nvidia-cuda-validator-jqwg5                                       0/1   Completed   0               2d1h
gpu-operator        nvidia-dcgm-exporter-5trpd                                        1/1   Running     1 (2d1h ago)    3d10h
gpu-operator        nvidia-dcgm-exporter-7sr6d                                        1/1   Running     1 (2d1h ago)    26d
gpu-operator        nvidia-device-plugin-daemonset-jc6m7                              1/1   Running     2 (2d1h ago)    3d10h
gpu-operator        nvidia-device-plugin-daemonset-xhm8t                              1/1   Running     1 (2d1h ago)    26d
gpu-operator        nvidia-operator-validator-lrq49                                   1/1   Running     1 (2d1h ago)    3d10h
gpu-operator        nvidia-operator-validator-vj67s                                   1/1   Running     1 (2d1h ago)    26d
grafana             grafana-84c4f8b575-c8bbx                                          3/3   Running     0               3h50m
humbleai-canary     humbleai-canary-7fdd77d9cb-jprzg                                  1/1   Running     1 (2d1h ago)    3d20h
humbleai            humbleai-75d4f4d646-wfgm4                                         1/1   Running     1 (2d1h ago)    6d21h
ingress-nginx       ingress-nginx-controller-8b668c484-t5bbj                          1/1   Running     0               4h54m
kanidm              kanidm-0                                                          1/1   Running     0               44h
kube-system         cilium-97b27                                                      1/1   Running     4 (2d1h ago)    30d
kube-system         cilium-bktjp                                                      1/1   Running     1 (2d1h ago)    30d
kube-system         cilium-c44ng                                                      1/1   Running     12 (44h ago)    30d
kube-system         cilium-h7cmt                                                      1/1   Running     8 (45h ago)     30d
kube-system         cilium-j64nq                                                      1/1   Running     9 (44h ago)     30d
kube-system         cilium-nwzq6                                                      1/1   Running     5 (2d1h ago)    25d
kube-system         cilium-operator-6999764665-dnh85                                  1/1   Running     20 (2d1h ago)   27d
kube-system         cilium-r8snc                                                      1/1   Running     7 (2d1h ago)    30d
kube-system         cilium-rgw2v                                                      1/1   Running     8 (2d1h ago)    30d
kube-system         cilium-v5gp5                                                      1/1   Running     1 (33h ago)     36h
kube-system         cilium-xwhxf                                                      1/1   Running     7 (2d1h ago)    30d
kube-system         coredns-6d8646cdb8-lj2xr                                          1/1   Running     0               45h
kube-system         hubble-relay-69f5fc5b79-zcbll                                     1/1   Running     0               44h
kube-system         hubble-ui-6548d56557-f9zkq                                        2/2   Running     0               44h
kube-system         kube-vip-bulbasaur                                                1/1   Running     59 (29h ago)    45d
kube-system         kube-vip-charmander                                               1/1   Running     59 (32h ago)    45d
kube-system         kube-vip-squirtle                                                 1/1   Running     59 (164m ago)   45d
kube-system         metrics-server-564cb4ff68-d9t5w                                   1/1   Running     1 (2d1h ago)    6d21h
kube-system         nfs-client-provisioner-nfs-subdir-external-provisioner-854mxccg   1/1   Running     5 (44h ago)     3d20h
kured               kured-4mx82                                                       1/1   Running     3 (44h ago)     5d13h
kured               kured-fmhx6                                                       1/1   Running     4 (44h ago)     5d13h
kured               kured-m9w56                                                       1/1   Running     3 (2d1h ago)    5d13h
kured               kured-vrtfq                                                       1/1   Running     3 (2d1h ago)    5d13h
kured               kured-wmqsk                                                       1/1   Running     4 (33h ago)     5d13h
kured               kured-xmvsm                                                       1/1   Running     3 (45h ago)     5d13h
kured               kured-zwxft                                                       1/1   Running     3 (2d1h ago)    5d13h
loki                loki-0                                                            1/1   Running     0               44h
loki                loki-promtail-79pqz                                               1/1   Running     21 (33h ago)    51d
loki                loki-promtail-b97xw                                               1/1   Running     19 (2d1h ago)   51d
loki                loki-promtail-bp6zx                                               1/1   Running     20 (45h ago)    51d
loki                loki-promtail-bsgzf                                               1/1   Running     20 (2d1h ago)   51d
loki                loki-promtail-gbjnm                                               1/1   Running     19 (2d1h ago)   51d
loki                loki-promtail-kqwwc                                               1/1   Running     4 (44h ago)     14d
loki                loki-promtail-tf7wq                                               1/1   Running     5 (2d1h ago)    25d
loki                loki-promtail-xwnbd                                               1/1   Running     24 (44h ago)    51d
monitoring-system   alertmanager-monitoring-system-kube-pro-alertmanager-0            3/3   Running     0               4h52m
monitoring-system   monitoring-system-kube-pro-operator-7d5594666c-2g7wf              1/1   Running     0               4h54m
monitoring-system   monitoring-system-kube-state-metrics-99859855-c28mf               1/1   Running     7 (2d1h ago)    5d13h
monitoring-system   monitoring-system-prometheus-node-exporter-2ff2b                  1/1   Running     3 (45h ago)     15d
monitoring-system   monitoring-system-prometheus-node-exporter-522wf                  1/1   Running     7 (44h ago)     15d
monitoring-system   monitoring-system-prometheus-node-exporter-7phcd                  1/1   Running     3 (2d1h ago)    4d1h
monitoring-system   monitoring-system-prometheus-node-exporter-86crd                  1/1   Running     3 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-j2h6q                  1/1   Running     4 (44h ago)     14d
monitoring-system   monitoring-system-prometheus-node-exporter-kpfww                  1/1   Running     1 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-pbqhg                  1/1   Running     3 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-pcv7h                  1/1   Running     4 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-x76df                  1/1   Running     3 (2d1h ago)    15d
monitoring-system   monitoring-system-prometheus-node-exporter-zhs9g                  1/1   Running     6 (33h ago)     15d
monitoring-system   prometheus-monitoring-system-kube-pro-prometheus-0                2/2   Running     0               4h54m
n8n                 n8n-db-849684747d-5c8wr                                           2/2   Running     3 (2d1h ago)    6d19h
n8n                 n8n-main-d586c6fcc-hlmkp                                          2/2   Running     0               36h
nextcloud           nextcloud-858b6cfdb7-lhhjf                                        2/2   Running     2 (2d1h ago)    3d20h
ollama              ollama-6cfccd7ff-lfn87                                            1/1   Running     0               4h55m
ollama              ollama-model-puller-868d6f7557-r2qgk                              1/1   Running     0               44h
openwebui           openwebui-54df8b6fd7-pcgf9                                        1/1   Running     0               44h
postgres            postgres-594559df7b-m8n5t                                         2/2   Running     2 (2d1h ago)    6d19h
qdrant              qdrant-0                                                          1/1   Running     1 (2d1h ago)    3d21h
radarr              radarr-f6666f9fc-mfr87                                            1/1   Running     1 (2d1h ago)    3d21h
renovate            renovate-29493540-9xsm2                                           0/1   Completed   0               38h
renovate            renovate-29494980-r9s99                                           0/1   Completed   0               14h
rook-ceph           ceph-csi-controller-manager-5dc6b7cf95-dd2z9                      1/1   Running     1 (43h ago)     44h
rook-ceph           rook-ceph-conversion-webhook-5b888b9f5d-2gld4                     1/1   Running     0               45h
rook-ceph           rook-ceph-crashcollector-arcanine-5d9d65b756-sbcd9                1/1   Running     0               5h7m
rook-ceph           rook-ceph-crashcollector-arcanine-7bcd8f5845-4nl4l                0/1   Completed   0               29d
rook-ceph           rook-ceph-crashcollector-bulbasaur-5479587f64-lsqlv               1/1   Running     0               5h8m
rook-ceph           rook-ceph-crashcollector-charmander-55579ddc5b-xbfft              1/1   Running     0               5h9m
rook-ceph           rook-ceph-crashcollector-chikorita-659f47b6f7-zlj6z               1/1   Running     0               5h6m
rook-ceph           rook-ceph-crashcollector-cyndaquil-5dbddfb65c-gjfxd               1/1   Running     0               5h9m
rook-ceph           rook-ceph-crashcollector-growlithe-8fccd9bd4-87mf2                1/1   Running     0               5h7m
rook-ceph           rook-ceph-crashcollector-sprigatito-846c5596b7-7w8fv              1/1   Running     0               5h6m
rook-ceph           rook-ceph-exporter-arcanine-5c744855c5-vs9q8                      1/1   Running     0               5h7m
rook-ceph           rook-ceph-exporter-bulbasaur-78bd56d849-kw8nh                     1/1   Running     0               5h8m
rook-ceph           rook-ceph-exporter-charmander-dc9b5dc-jz4v6                       1/1   Running     0               5h9m
rook-ceph           rook-ceph-exporter-chikorita-6479bb6484-789nl                     1/1   Running     0               5h6m
rook-ceph           rook-ceph-exporter-cyndaquil-6597d4d54d-kchqq                     1/1   Running     0               5h9m
rook-ceph           rook-ceph-exporter-growlithe-7ffff74c85-jfb6l                     1/1   Running     0               5h7m
rook-ceph           rook-ceph-exporter-sprigatito-bb57879c6-j8lg7                     1/1   Running     0               5h6m
rook-ceph           rook-ceph-mds-standard-rwx-a-6bd6586df-vlkc2                      1/1   Running     0               5h7m
rook-ceph           rook-ceph-mds-standard-rwx-b-779b85d79c-7tbdh                     1/1   Running     0               5h7m
rook-ceph           rook-ceph-mgr-a-58d8898ccb-qwrml                                  2/2   Running     0               5h7m
rook-ceph           rook-ceph-mgr-b-66cb475bb6-5fbcq                                  2/2   Running     0               5h6m
rook-ceph           rook-ceph-mon-f-5cc966c797-4prh4                                  1/1   Running     0               5h8m
rook-ceph           rook-ceph-mon-h-5ccccdb9bc-qsj9n                                  1/1   Running     0               5h9m
rook-ceph           rook-ceph-mon-j-746c974688-v875x                                  1/1   Running     0               5h9m
rook-ceph           rook-ceph-operator-fd5bd8dff-xcjsq                                1/1   Running     0               45h
rook-ceph           rook-ceph-osd-0-759886b475-c6bpv                                  1/1   Running     0               5h5m
rook-ceph           rook-ceph-osd-1-6d8c5776bc-jxczh                                  1/1   Running     0               5h3m
rook-ceph           rook-ceph-osd-2-65c544f9b9-fgscb                                  1/1   Running     0               5h4m
rook-ceph           rook-ceph-osd-4-68899c7d97-prb47                                  1/1   Running     0               5h5m
rook-ceph           rook-ceph-osd-6-84797665c5-w5vjb                                  1/1   Running     0               5h4m
rook-ceph           rook-ceph-osd-7-7f4d84c6d6-v2qcd                                  1/1   Running     0               5h5m
rook-ceph           rook-ceph-osd-8-5b654b7fd6-qb8xb                                  1/1   Running     0               5h4m
rook-ceph           rook-ceph-osd-prepare-arcanine-qxj8z                              0/1   Completed   0               4h59m
rook-ceph           rook-ceph-osd-prepare-bulbasaur-xh2cj                             0/1   Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-charmander-hcb4m                            0/1   Completed   0               4h59m
rook-ceph           rook-ceph-osd-prepare-chikorita-pf6gb                             0/1   Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-cyndaquil-8k5vz                             0/1   Completed   0               4h59m
rook-ceph           rook-ceph-osd-prepare-growlithe-ccwzb                             0/1   Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-pikachu-z5qhb                               0/1   Completed   0               4h58m
rook-ceph           rook-ceph-osd-prepare-sprigatito-l6h57                            0/1   Completed   0               4h59m
rook-ceph           rook-ceph-osd-prepare-squirtle-fdtql                              0/1   Completed   0               4h59m
rook-ceph           rook-ceph-osd-prepare-totodile-56x6g                              0/1   Completed   0               4h58m
rook-ceph           rook-ceph-snapshot-controller-7dd476c4f9-978ph                    1/1   Running     1 (43h ago)     44h
rook-ceph           rook-ceph-tools-658fd4db6f-74q5z                                  1/1   Running     0               45h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-ctrlplugin-c4dc99579-hgs9w          5/5   Running     5 (2d1h ago)    3d20h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-ctrlplugin-c4dc99579-rgxgl          5/5   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-76n4p                    2/2   Running     12 (44h ago)    5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-8ksjd                    2/2   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-fkbgp                    2/2   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-g7lg6                    2/2   Running     0               33h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-jd8ls                    2/2   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-kbgmg                    2/2   Running     40 (45h ago)    5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-qd5mh                    2/2   Running     7 (2d ago)      5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-wtkt4                    2/2   Running     20 (2d1h ago)   5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-xmllg                    2/2   Running     12 (44h ago)    5d13h
rook-ceph           rook-ceph.cephfs.csi.ceph.com-nodeplugin-z87qn                    2/2   Running     4 (2d1h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-ctrlplugin-5f745fd754-gbkmt            5/5   Running     0               45h
rook-ceph           rook-ceph.rbd.csi.ceph.com-ctrlplugin-5f745fd754-pgc79            5/5   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-2f4hm                       2/2   Running     4 (2d1h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-8kbsv                       2/2   Running     16 (2d1h ago)   4d2h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-9tqz8                       2/2   Running     0               33h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-cg6w5                       2/2   Running     37 (45h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-cx6dd                       2/2   Running     12 (44h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-frbtp                       2/2   Running     9 (2d ago)      5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-hlqmn                       2/2   Running     12 (44h ago)    5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-qq6d4                       2/2   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-vpgch                       2/2   Running     12 (2d1h ago)   5d13h
rook-ceph           rook-ceph.rbd.csi.ceph.com-nodeplugin-x5gzh                       2/2   Running     12 (2d1h ago)   5d13h
sabnzbd             sabnzbd-854686f555-h7nzf                                          2/2   Running     0               44h
sabnzbd             sabnzbd-f7456ffcd-v5smd                                           2/2   Running     0               44h
searxng             searxng-main-85d6c58b8c-gdjj6                                     1/1   Running     0               44h
searxng             searxng-redis-5b5d46bf8c-vsbzd                                    1/1   Running     1 (2d1h ago)    6d18h
sonarr              sonarr-6d44cd4845-h2nk2                                           1/1   Running     0               44h
volsync-system      volsync-system-5db49859d-7wp4c                                    2/2   Running     2 (2d1h ago)    3d20h
weaviate-test       weaviate-0                                                        1/1   Running     0               44h
woodpecker          woodpecker-agent-0                                                1/1   Running     22 (47h ago)    3d20h
woodpecker          woodpecker-server-0                                               1/1   Running     1 (33h ago)     36h
zot                 zot-0                                                             1/1   Running     0               4h55m
```

## `60_problem_pods.txt`

```text

```

## `61_services_all.txt`

```text
NAMESPACE           NAME                                                 TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)                                   AGE
argocd              argocd-application-controller-metrics                ClusterIP      10.43.150.180   <none>        8082/TCP                                  52d
argocd              argocd-applicationset-controller                     ClusterIP      10.43.209.103   <none>        7000/TCP                                  52d
argocd              argocd-dex-server                                    ClusterIP      10.43.107.60    <none>        5556/TCP,5557/TCP                         52d
argocd              argocd-redis                                         ClusterIP      10.43.117.67    <none>        6379/TCP                                  52d
argocd              argocd-redis-metrics                                 ClusterIP      None            <none>        9121/TCP                                  52d
argocd              argocd-repo-server                                   ClusterIP      10.43.110.4     <none>        8081/TCP                                  52d
argocd              argocd-repo-server-metrics                           ClusterIP      10.43.150.225   <none>        8084/TCP                                  52d
argocd              argocd-server                                        ClusterIP      10.43.208.67    <none>        80/TCP,443/TCP                            52d
argocd              argocd-server-metrics                                ClusterIP      10.43.63.246    <none>        8083/TCP                                  52d
backlog-canary      backlog-canary-backend                               ClusterIP      10.43.232.161   <none>        3000/TCP                                  25d
backlog-canary      backlog-canary-database                              ClusterIP      10.43.205.14    <none>        3306/TCP                                  25d
backlog-canary      backlog-canary-main                                  ClusterIP      10.43.112.80    <none>        80/TCP                                    25d
backlog             backlog-backend                                      ClusterIP      10.43.175.227   <none>        3000/TCP                                  25d
backlog             backlog-database                                     ClusterIP      10.43.201.99    <none>        3306/TCP                                  25d
backlog             backlog-main                                         ClusterIP      10.43.32.104    <none>        80/TCP                                    25d
budget-canary       budget-canary-backend                                ClusterIP      10.43.188.72    <none>        3001/TCP                                  31d
budget-canary       budget-canary-main                                   ClusterIP      10.43.158.233   <none>        80/TCP                                    31d
budget              budget-backend                                       ClusterIP      10.43.140.37    <none>        3001/TCP                                  30d
budget              budget-main                                          ClusterIP      10.43.99.84     <none>        80/TCP                                    30d
cert-manager        cert-manager                                         ClusterIP      10.43.44.128    <none>        9402/TCP                                  52d
cert-manager        cert-manager-cainjector                              ClusterIP      10.43.225.221   <none>        9402/TCP                                  51d
cert-manager        cert-manager-webhook                                 ClusterIP      10.43.221.39    <none>        443/TCP,9402/TCP                          52d
code                weaviate                                             LoadBalancer   10.43.176.74    10.0.20.229   80:31667/TCP                              149d
code                weaviate-grpc                                        LoadBalancer   10.43.88.51     10.0.20.225   50051:31271/TCP                           149d
code                weaviate-headless                                    ClusterIP      None            <none>        80/TCP                                    149d
connect             onepassword-connect                                  NodePort       10.43.223.130   <none>        8081:31195/TCP,8080:32553/TCP             52d
default             external-secrets-webhook                             ClusterIP      10.43.159.20    <none>        443/TCP                                   51d
default             kubernetes                                           ClusterIP      10.43.0.1       <none>        443/TCP                                   342d
dex                 dex                                                  ClusterIP      10.43.203.7     <none>        5556/TCP,5558/TCP                         52d
emby                emby                                                 ClusterIP      10.43.174.205   <none>        8096/TCP,8920/TCP                         52d
explorers-hub       explorers-hub                                        ClusterIP      10.43.120.12    <none>        80/TCP                                    41d
external-dns        external-dns                                         ClusterIP      10.43.117.209   <none>        7979/TCP                                  52d
external-secrets    external-secrets-webhook                             ClusterIP      10.43.199.156   <none>        443/TCP                                   52d
gitea               gitea-http                                           ClusterIP      None            <none>        3000/TCP                                  52d
gitea               gitea-postgresql                                     ClusterIP      10.43.99.56     <none>        5432/TCP                                  52d
gitea               gitea-postgresql-hl                                  ClusterIP      None            <none>        5432/TCP                                  52d
gitea               gitea-ssh                                            ClusterIP      None            <none>        22/TCP                                    52d
gitea               gitea-valkey-cluster                                 ClusterIP      10.43.161.147   <none>        6379/TCP                                  52d
gitea               gitea-valkey-cluster-headless                        ClusterIP      None            <none>        6379/TCP,16379/TCP                        52d
gpu-operator        gpu-operator                                         ClusterIP      10.43.88.89     <none>        8080/TCP                                  52d
gpu-operator        gpu-operator-node-feature-discovery-master           ClusterIP      10.43.125.62    <none>        8080/TCP                                  52d
gpu-operator        nvidia-dcgm-exporter                                 ClusterIP      10.43.174.29    <none>        9400/TCP                                  52d
grafana             grafana                                              ClusterIP      10.43.61.201    <none>        80/TCP                                    52d
humbleai-canary     humbleai-canary-api                                  ClusterIP      10.43.32.147    <none>        3001/TCP                                  52d
humbleai-canary     humbleai-canary-main                                 ClusterIP      10.43.117.11    <none>        3000/TCP                                  52d
humbleai            humbleai-api                                         ClusterIP      10.43.72.221    <none>        3001/TCP                                  52d
humbleai            humbleai-main                                        ClusterIP      10.43.120.8     <none>        3000/TCP                                  52d
ingress-nginx       ingress-nginx-controller                             LoadBalancer   10.43.151.100   10.0.20.226   80:30242/TCP,443:31665/TCP,22:30840/TCP   45d
ingress-nginx       ingress-nginx-controller-admission                   ClusterIP      10.43.63.5      <none>        443/TCP                                   52d
ingress-nginx       ingress-nginx-controller-metrics                     ClusterIP      10.43.57.130    <none>        10254/TCP                                 52d
kanidm              kanidm                                               ClusterIP      10.43.175.231   <none>        443/TCP,636/TCP                           52d
kube-system         hubble-peer                                          ClusterIP      10.43.220.7     <none>        443/TCP                                   342d
kube-system         hubble-relay                                         ClusterIP      10.43.61.204    <none>        80/TCP                                    342d
kube-system         hubble-ui                                            ClusterIP      10.43.116.155   <none>        80/TCP                                    342d
kube-system         kube-dns                                             ClusterIP      10.43.0.10      <none>        53/UDP,53/TCP,9153/TCP                    342d
kube-system         metrics-server                                       ClusterIP      10.43.50.79     <none>        443/TCP                                   342d
kube-system         monitoring-system-kube-pro-coredns                   ClusterIP      None            <none>        9153/TCP                                  15d
kube-system         monitoring-system-kube-pro-kube-controller-manager   ClusterIP      None            <none>        10257/TCP                                 15d
kube-system         monitoring-system-kube-pro-kube-etcd                 ClusterIP      None            <none>        2381/TCP                                  15d
kube-system         monitoring-system-kube-pro-kube-proxy                ClusterIP      None            <none>        10249/TCP                                 15d
kube-system         monitoring-system-kube-pro-kube-scheduler            ClusterIP      None            <none>        10259/TCP                                 15d
kube-system         monitoring-system-kube-pro-kubelet                   ClusterIP      None            <none>        10250/TCP,10255/TCP,4194/TCP              341d
localai             localai-local-ai                                     ClusterIP      10.43.125.61    <none>        8080/TCP                                  52d
loki                loki                                                 ClusterIP      10.43.100.101   <none>        3100/TCP                                  52d
loki                loki-headless                                        ClusterIP      None            <none>        3100/TCP                                  52d
loki                loki-memberlist                                      ClusterIP      None            <none>        7946/TCP                                  52d
monitoring-system   alertmanager-operated                                ClusterIP      None            <none>        9093/TCP,9094/TCP,9094/UDP                15d
monitoring-system   monitoring-system-kube-pro-alertmanager              ClusterIP      10.43.37.243    <none>        9093/TCP,8080/TCP                         15d
monitoring-system   monitoring-system-kube-pro-operator                  ClusterIP      10.43.100.145   <none>        443/TCP                                   15d
monitoring-system   monitoring-system-kube-pro-prometheus                ClusterIP      10.43.248.189   <none>        9090/TCP,8080/TCP                         15d
monitoring-system   monitoring-system-kube-state-metrics                 ClusterIP      10.43.64.9      <none>        8080/TCP                                  15d
monitoring-system   monitoring-system-prometheus-node-exporter           ClusterIP      10.43.249.174   <none>        9100/TCP                                  15d
monitoring-system   prometheus-operated                                  ClusterIP      None            <none>        9090/TCP                                  15d
n8n                 n8n-db                                               ClusterIP      10.43.91.13     <none>        5432/TCP                                  29d
n8n                 n8n-main                                             ClusterIP      10.43.93.45     <none>        5678/TCP                                  28d
nextcloud           nextcloud                                            ClusterIP      10.43.249.172   <none>        443/TCP                                   39d
ollama              ollama                                               ClusterIP      10.43.158.161   <none>        11434/TCP                                 3d10h
openwebui           openwebui                                            ClusterIP      10.43.227.37    <none>        8080/TCP                                  52d
postgres            postgres                                             ClusterIP      10.43.213.83    <none>        5432/TCP                                  39d
qdrant              qdrant                                               ClusterIP      10.43.180.247   <none>        6334/TCP,6333/TCP                         47d
radarr              radarr                                               ClusterIP      10.43.198.87    <none>        7878/TCP                                  52d
rook-ceph           rook-ceph-conversion-webhook                         ClusterIP      10.43.133.154   <none>        443/TCP                                   14d
rook-ceph           rook-ceph-exporter                                   ClusterIP      10.43.48.23     <none>        9926/TCP                                  52d
rook-ceph           rook-ceph-mgr                                        ClusterIP      10.43.148.164   <none>        9283/TCP                                  52d
rook-ceph           rook-ceph-mgr-dashboard                              ClusterIP      10.43.241.96    <none>        7000/TCP                                  52d
rook-ceph           rook-ceph-mon-f                                      ClusterIP      10.43.153.86    <none>        6789/TCP,3300/TCP                         52d
rook-ceph           rook-ceph-mon-h                                      ClusterIP      10.43.243.67    <none>        6789/TCP,3300/TCP                         47d
rook-ceph           rook-ceph-mon-j                                      ClusterIP      10.43.217.162   <none>        6789/TCP,3300/TCP                         17d
sabnzbd             sabnzbd                                              ClusterIP      10.43.94.8      <none>        8080/TCP                                  52d
searxng             searxng                                              ClusterIP      10.43.128.247   <none>        8080/TCP                                  52d
searxng             searxng-main                                         ClusterIP      10.43.181.76    <none>        8080/TCP                                  28d
searxng             searxng-redis                                        ClusterIP      10.43.83.253    <none>        6379/TCP                                  52d
sonarr              sonarr                                               ClusterIP      10.43.237.12    <none>        8989/TCP                                  52d
volsync-system      volsync-system-metrics                               ClusterIP      10.43.163.15    <none>        8443/TCP                                  52d
weaviate-test       weaviate                                             LoadBalancer   10.43.254.79    10.0.20.227   80:32447/TCP                              149d
weaviate-test       weaviate-grpc                                        LoadBalancer   10.43.172.180   10.0.20.228   50051:31738/TCP                           149d
weaviate-test       weaviate-headless                                    ClusterIP      None            <none>        80/TCP                                    149d
woodpecker          woodpecker-server                                    ClusterIP      10.43.172.240   <none>        80/TCP,9000/TCP                           52d
woodpecker          woodpecker-server-headless                           ClusterIP      None            <none>        80/TCP,9000/TCP                           52d
zot                 zot                                                  NodePort       10.43.60.181    <none>        5000:32309/TCP                            52d
```

## `70_open_prs.json`

```text
[]
```

## `71_open_prs.txt`

```text

```

## `72_open_prs_detailed.json`

```text
[]
```

## `73_open_issues.json`

```text
[{"id":16,"url":"https://git.eaglepass.io/api/v1/repos/ops/homelab/issues/4","html_url":"https://git.eaglepass.io/ops/homelab/issues/4","number":4,"user":{"id":1,"login":"gitea_admin","login_name":"","source_id":0,"full_name":"","email":"gitea@local.domain","avatar_url":"https://git.eaglepass.io/avatars/0642e3e25d9a91d2519388e6e4dbc915","html_url":"https://git.eaglepass.io/gitea_admin","language":"en-US","is_admin":true,"last_login":"2026-01-28T23:23:55Z","created":"2025-10-15T15:27:42Z","restricted":false,"active":true,"prohibit_login":false,"location":"","website":"","description":"","visibility":"public","followers_count":0,"following_count":0,"starred_repos_count":0,"username":"gitea_admin"},"original_author":"","original_author_id":0,"title":"Dependency Dashboard","body":"This issue lists Renovate updates and detected dependencies. Read the [Dependency Dashboard](https://docs.renovatebot.com/key-concepts/dashboard/) docs to learn more.\n\n## Repository Problems\n\nRenovate tried to run on this repository, but found these problems.\n\n - ⚠️ WARN: GitHub token is required for some dependencies\n - ⚠️ WARN: No github.com token has been configured. Skipping release notes retrieval\n\n## Open\n\nThe following updates have all been created. To force a retry/rebase of any, click on a checkbox below.\n\n - [ ] \u003c!-- rebase-branch=renovate/all-minor-patch --\u003e[chore(deps): update all non-major dependencies](pulls/50) (`argo-cd`, `docker.io/cloudflare/cloudflared`, `docker.io/library/alpine`, `docker.io/library/busybox`, `external-secrets`, `gitea`, `grafana`, `ingress-nginx`, `kube-prometheus-stack`, `ollama`, `renovate`, `supabase/gotrue`, `supabase/logflare`, `supabase/postgres`, `supabase/realtime`, `supabase/storage-api`, `timberio/vector`, `zot`)\n - [ ] \u003c!-- rebase-branch=renovate/docker.io-library-debian-13.x --\u003e[chore(deps): update docker.io/library/debian docker tag to v13](pulls/52)\n - [ ] \u003c!-- rebase-branch=renovate/quay.io-ceph-ceph-20.x --\u003e[chore(deps): update quay.io/ceph/ceph docker tag to v20](pulls/51)\n - [ ] \u003c!-- rebase-all-open-prs --\u003e**Click on this checkbox to rebase all open PRs at once**\n\n## Detected Dependencies\n\n\u003cdetails\u003e\u003csummary\u003edocker-compose (2)\u003c/summary\u003e\n\u003cblockquote\u003e\n\n\u003cdetails\u003e\u003csummary\u003edocker-compose.yml (13)\u003c/summary\u003e\n\n - `supabase/studio 2025.06.30-sha-6f5982d`\n - `kong 3.9.1`\n - `supabase/gotrue v2.185.0` → [Updates: `v2.186.0`]\n - `postgrest/postgrest v13.0.8`\n - `supabase/realtime v2.71.4` → [Updates: `v2.73.3`]\n - `supabase/storage-api v1.33.5` → [Updates: `v1.35.3`]\n - `darthsim/imgproxy v3.30.1`\n - `supabase/postgres-meta v0.95.2`\n - `supabase/edge-runtime v1.70.0`\n - `supabase/logflare 1.30.0` → [Updates: `1.30.5`]\n - `supabase/postgres 17.6.1.072` → [Updates: `17.6.1.074`]\n - `timberio/vector 0.52.0-alpine` → [Updates: `0.53.0-alpine`]\n - `supabase/supavisor 2.7.4`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003emetal/roles/pxe_server/files/docker-compose.yml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003c/blockquote\u003e\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003edockerfile (7)\u003c/summary\u003e\n\u003cblockquote\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/n8n/Dockerfile (1)\u003c/summary\u003e\n\n - `postgres 18.1-bookworm`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/committee-training/Dockerfile (1)\u003c/summary\u003e\n\n - `pytorch/pytorch 2.6.0-cuda12.4-cudnn9-runtime`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/elysia/Dockerfile (1)\u003c/summary\u003e\n\n - `python 3.14-slim`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/heartlib/Dockerfile (2)\u003c/summary\u003e\n\n - `nvidia/cuda 13.1.1-devel-ubuntu22.04`\n - `nvidia/cuda 13.1.1-runtime-ubuntu22.04`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/exo/Dockerfile (1)\u003c/summary\u003e\n\n - `python 3.14-slim`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003emetal/roles/pxe_server/files/dnsmasq/Dockerfile (1)\u003c/summary\u003e\n\n - `alpine 3.23`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003emetal/roles/pxe_server/files/http/Dockerfile (1)\u003c/summary\u003e\n\n - `nginx 1.29-alpine`\n\n\u003c/details\u003e\n\n\u003c/blockquote\u003e\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003egomod (2)\u003c/summary\u003e\n\u003cblockquote\u003e\n\n\u003cdetails\u003e\u003csummary\u003eplatform/gitea/files/config/go.mod (4)\u003c/summary\u003e\n\n - `go 1.19`\n - `code.gitea.io/sdk/gitea v0.22.1`\n - `gopkg.in/yaml.v3 v3.0.1`\n - `gopkg.in/yaml.v3 v3.0.1`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eplatform/global-secrets/files/secret-generator/go.mod (7)\u003c/summary\u003e\n\n - `go 1.25.0`\n - `go 1.25.6`\n - `github.com/sethvargo/go-password v0.3.1`\n - `gopkg.in/yaml.v3 v3.0.1`\n - `k8s.io/api v0.35.0`\n - `k8s.io/apimachinery v0.35.0`\n - `k8s.io/client-go v0.35.0`\n\n\u003c/details\u003e\n\n\u003c/blockquote\u003e\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003ehelm-values (76)\u003c/summary\u003e\n\u003cblockquote\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/backlog-canary/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/backlog/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/budget-canary/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/budget/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/doplarr/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/emby/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/explorers-hub/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/humbleai-canary/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/humbleai/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/moltbot/values.yaml (3)\u003c/summary\u003e\n\n - `docker.io/library/busybox 1.36.1` → [Updates: `1.37.0`]\n - `docker.io/library/debian 12-slim` → [Updates: `13-slim`]\n - `docker.io/library/alpine 3.20` → [Updates: `3.23`]\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/n8n/values.yaml (2)\u003c/summary\u003e\n\n - `docker.io/brimdor/postgres 17.5-bookworm`\n - `postgres 18.1-bookworm`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/nextcloud/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/ollama/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/openwebui/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/postgres/values.yaml (2)\u003c/summary\u003e\n\n - `docker.io/brimdor/postgres 17.5-bookworm`\n - `postgres 18.1-bookworm`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/qdrant/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/radarr/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/sabnzbd/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/searxng/values.yaml (1)\u003c/summary\u003e\n\n - `valkey/valkey 9-alpine`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/sonarr/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/agent-zero/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/altus/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/astroneer/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/backlog/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/bolt/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/browser-use-canary/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/browser-use/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/code-canary/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/code/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/color-race/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/comfyui/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/deepcode/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/elysia/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/emby-companion/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/embystat/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/family-games-host/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/family-games-rules/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/heartlib/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/homehub/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/homepage/values.yaml (1)\u003c/summary\u003e\n\n - `ghcr.io/gethomepage/homepage v1.9.0`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/kagent/values.yaml (2)\u003c/summary\u003e\n\n - `ghcr.io/kagent-dev/kagent/tools 0.0.13`\n - `ghcr.io/kagent-dev/doc2vec/mcp v1.1.14`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/kali-linux/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/kavita/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/livekit/values.yaml (1)\u003c/summary\u003e\n\n - `redis 8.4-alpine`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/localai/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/mcpo/values.yaml (1)\u003c/summary\u003e\n\n - `alpine 3.23`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/media-cleaner/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/minecraft/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/n8n-OLD/values.yaml (2)\u003c/summary\u003e\n\n - `postgres 18-alpine`\n - `postgres 18-alpine`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/nextcloud/values.yaml (1)\u003c/summary\u003e\n\n - `mariadb 12.1`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/nibble/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/obsidian/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/OLDsteam-headless/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/ombi/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/omni-tools/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/open-notebook/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/opencode/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/peppermint/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/pigeon-pod/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/planka/values.yaml (1)\u003c/summary\u003e\n\n - `ghcr.io/plankanban/planka 2.0.0-rc.3`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/pterodactyl/values.yaml (1)\u003c/summary\u003e\n\n - `yoshiwalsh/pterodactyl-panel v1.11.10`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/rocket/values.yaml (3)\u003c/summary\u003e\n\n - `registry.rocket.chat/rocketchat/rocket.chat 8.0.1`\n - `mongo 8`\n - `mongo 8`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/sherlock/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/sim/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/skyfactory5/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/speedtest/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/supabase/values.yaml (3)\u003c/summary\u003e\n\n - `supabase/postgres 17.6.1.072` → [Updates: `17.6.1.074`]\n - `supabase/postgres-meta v0.95.2`\n - `supabase/edge-runtime v1.70.0`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/ubuntu-mate/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/wolf/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/exo/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eplatform/kanidm/values.yaml (1)\u003c/summary\u003e\n\n - `docker.io/kanidm/server 1.8.5`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/cloudflared/values.yaml (1)\u003c/summary\u003e\n\n - `docker.io/cloudflare/cloudflared 2026.1.1` → [Updates: `2026.1.2`]\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/gpu-operator/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/kured/values.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/monitoring-system/values.yaml (1)\u003c/summary\u003e\n\n - `ghcr.io/khuedoan/webhook-transformer v0.0.3`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/rook-ceph/values.yaml (1)\u003c/summary\u003e\n\n - `quay.io/ceph/ceph v19.2.3` → [Updates: `v20.2.0`]\n\n\u003c/details\u003e\n\n\u003c/blockquote\u003e\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003ehelmv3 (80)\u003c/summary\u003e\n\u003cblockquote\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/backlog-canary/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/backlog/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/budget-canary/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/budget/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/emby/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/explorers-hub/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/humbleai-canary/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/humbleai/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/moltbot/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/n8n/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/nextcloud/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/ollama/Chart.yaml (1)\u003c/summary\u003e\n\n - `ollama 1.38.0` → [Updates: `1.39.0`]\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/openwebui/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/postgres/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/qdrant/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/radarr/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/sabnzbd/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/searxng/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eapps/sonarr/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/agent-zero/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/altus/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/astroneer/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/backlog/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/bolt/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/browser-use-canary/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/browser-use/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/code-canary/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/code/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/color-race/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/comfyui/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/deepcode/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/elysia/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/embystat/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/family-games-host/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/family-games-rules/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/heartlib/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/homehub/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/homepage/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/kavita/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/localai/Chart.yaml (1)\u003c/summary\u003e\n\n - `local-ai \u003e=3.3.0 \u003c4.0.0`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/matrix/Chart.yaml (2)\u003c/summary\u003e\n\n - `elementweb 0.0.6`\n - `dendrite 0.14.6`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/mcpo/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/media-cleaner/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/n8n-OLD/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/nextcloud/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/nibble/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/obsidian/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/OLDsteam-headless/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/omni-tools/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/open-notebook/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/opencode/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/peppermint/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/pigeon-pod/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/planka/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/pterodactyl/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/rocket/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/sherlock/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/speedtest/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/weaviate/Chart.yaml (1)\u003c/summary\u003e\n\n - `weaviate \u003e= 1.0.0`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/apps/wolf/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003earchived/exo/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eplatform/dex/Chart.yaml (1)\u003c/summary\u003e\n\n - `dex 0.24.0`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eplatform/external-secrets/Chart.yaml (1)\u003c/summary\u003e\n\n - `external-secrets 1.2.1` → [Updates: `1.3.1`]\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eplatform/gitea/Chart.yaml (1)\u003c/summary\u003e\n\n - `gitea 12.4.0` → [Updates: `12.5.0`]\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eplatform/grafana/Chart.yaml (1)\u003c/summary\u003e\n\n - `grafana 10.5.12` → [Updates: `10.5.14`]\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eplatform/kanidm/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eplatform/renovate/Chart.yaml (1)\u003c/summary\u003e\n\n - `renovate 45.85.0` → [Updates: `45.88.1`]\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eplatform/woodpecker/Chart.yaml (1)\u003c/summary\u003e\n\n - `woodpecker 3.5.1`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eplatform/zot/Chart.yaml (1)\u003c/summary\u003e\n\n - `zot 0.1.95` → [Updates: `0.1.97`]\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/argocd/Chart.yaml (2)\u003c/summary\u003e\n\n - `argo-cd 9.3.5` → [Updates: `9.3.7`]\n - `argocd-apps 2.0.4`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/cert-manager/Chart.yaml (1)\u003c/summary\u003e\n\n - `cert-manager v1.19.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/cloudflared/Chart.yaml (1)\u003c/summary\u003e\n\n - `app-template 4.6.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/external-dns/Chart.yaml (1)\u003c/summary\u003e\n\n - `external-dns 1.20.0`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/gpu-operator/Chart.yaml (1)\u003c/summary\u003e\n\n - `node-feature-discovery 0.18.3`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/ingress-nginx/Chart.yaml (1)\u003c/summary\u003e\n\n - `ingress-nginx 4.14.1` → [Updates: `4.14.2`]\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/kured/Chart.yaml (1)\u003c/summary\u003e\n\n - `kured 5.11.0`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/loki/Chart.yaml (1)\u003c/summary\u003e\n\n - `loki-stack 2.10.3`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/monitoring-system/Chart.yaml (1)\u003c/summary\u003e\n\n - `kube-prometheus-stack 81.2.1` → [Updates: `81.3.0`]\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/rook-ceph/Chart.yaml (3)\u003c/summary\u003e\n\n - `rook-ceph v1.19.0`\n - `rook-ceph-cluster v1.19.0`\n - `snapshot-controller 5.0.2`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003esystem/volsync-system/Chart.yaml (1)\u003c/summary\u003e\n\n - `volsync 0.14.0`\n\n\u003c/details\u003e\n\n\u003c/blockquote\u003e\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eterraform (5)\u003c/summary\u003e\n\u003cblockquote\u003e\n\n\u003cdetails\u003e\u003csummary\u003eexternal/main.tf\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eexternal/modules/cloudflare/versions.tf (3)\u003c/summary\u003e\n\n - `cloudflare ~\u003e 5.16.0`\n - `http ~\u003e 3.5.0`\n - `kubernetes ~\u003e 3.0.0`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eexternal/modules/extra-secrets/versions.tf (1)\u003c/summary\u003e\n\n - `kubernetes ~\u003e 3.0.0`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eexternal/modules/ntfy/versions.tf (1)\u003c/summary\u003e\n\n - `kubernetes ~\u003e 3.0.0`\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003eexternal/versions.tf (3)\u003c/summary\u003e\n\n - `cloudflare ~\u003e 5.16.0`\n - `http ~\u003e 3.5.0`\n - `kubernetes ~\u003e 3.0.0`\n\n\u003c/details\u003e\n\n\u003c/blockquote\u003e\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003ewoodpecker (2)\u003c/summary\u003e\n\u003cblockquote\u003e\n\n\u003cdetails\u003e\u003csummary\u003e.woodpecker/helm-diff.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003cdetails\u003e\u003csummary\u003e.woodpecker/static-checks.yaml\u003c/summary\u003e\n\n\n\u003c/details\u003e\n\n\u003c/blockquote\u003e\n\u003c/details\u003e\n\n","ref":"","assets":[],"labels":[],"milestone":null,"assignee":null,"assignees":null,"state":"open","is_locked":false,"comments":0,"created_at":"2025-12-09T15:01:32Z","updated_at":"2026-01-29T22:10:19Z","closed_at":null,"due_date":null,"time_estimate":0,"pull_request":null,"repository":{"id":5,"name":"homelab","owner":"ops","full_name":"ops/homelab"},"pin_order":0}]
```

## `74_open_issues_nonmaintenance.txt`

```text
Issue #4: Dependency Dashboard
```
