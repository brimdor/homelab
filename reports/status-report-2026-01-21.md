# Homelab Status Report - EXHAUSTIVE Maintenance (2026-01-21)

## Cluster Health (All GREEN ✅ except muted Ceph warning) **Except:** 
- (P0) containerd-stargz image inspection failure
- (P0) NFS stale file handle (delegation failed)

---

## Current Issues Blocking GREEN ✅

### Phase 1: Critical (Immediate Fix Required)

#### Issue #1 - Image Inspection Failure ✅ (**CRITICAL:** Affects ALL pods on affected nodes)
`**contained-stargz-grpc.sock connection refused on chikorita**` 
* **Evidence:** Two pods (grafana, nfs-provisioner) in `ImageInspectError` on the same node
* **Cause:** containerd-stargz service miscommunication → pod inspection fails
* **Impact Area:** `chikorita`
* **Workaround:** Reimage or move non-critical apps to alternate nodes
* **Action:** Requires `**A1 P0 -- Fix containerd-stargz`**

#### Issue #2 - NFS Stale File Handle (Heartlib) ✅ (**CRITICAL**)
`**Stale NFS file handle on arcanine**` 
* **Evidence:** A persistent `heartlib` pod crashing in startup due to stale handle
* **Impact Area:** `arcanine`
* **Workaround:** Manually reconnect NFS paths or relocate Heartlib workload
* **Action:** Requires `**B1 P0 -- Fix stale NFS handle`


---

## Phase 2: System Layer (Post-Resolution)
**✅ No failing services detected except Heartlib and Grafana**

- Ceph: **`HEALTH_OK (muted: DB_DEVICE_STALLED_READ_ALERT)`** 
- ArgoCD: **37/39 apps Synced+Healthy**
- Core PODs: All Running
- CertManager: All 26/26 certificates READY

--- 

## Recommended Action Items

### Task 1 (**A1 P0**) - Fix containerd-stargz on chikorita
* **Command:** ```bash
kubectl exec chikorita -- rm -rf /run/user/* && systemctl restart containerd
```
* **Failure Case:** Manual intervention needed
* **Rollback:** Move Grafana to bulbasaur; provisioner to arcane (alternate node)

### Task 2 (**B2 P0**) - Remediate stale NFS handle on arcanine
* **Command:** 
```bash
kubectl debug -i -t heartbeatlib-debugger --image=ubuntu --target=heartlib
apt-get update && apt-get install -y nfs-common
apt-get install cifs utils
mount -t nfs:4.1 10.0.40.3:/mnt/user/heartlib/models /mnt/heartlib/models
chmod +x /mnt/heartlib/models
```
- **Stop Condition:** Heartlib pod resumes normal startup


## Maintenance Checkboxes Alignment

**Action Items Phase (All Top-Level)**

- **[ ]** *A1 P0:* Restart containerd on chikorita + recover impacted pods
- **[ ]** *A2 P0:* Resync Heartlib NFS mount + verify persistent handle
- **[ ]** *C10 P0:* **Reboot ArgoCD Arcs & check app sync status**
- **[ ]** *D1 P0:* Run `/homelab-recon` on all nodes with `--strict`

## Evidence Snapshot

- **Nodes:** All ready ✅
- **Ceph:** HEALTH_OK ✅ but muted warning remains (review later)
- **Repo Sync:** No critical findings
- **Repo Access:** MCP/Gitea issue **pending** 

> **Critical:** **No GREEN for now until Tasks A1 & B2 are complete**