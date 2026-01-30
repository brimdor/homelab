# 🚀 Homelab Fedora 43 Upgrade Strategy

**Version:** 2.0.0
**Date:** 2026-01-30
**Target OS:** Fedora Linux 43 (Rawhide/Bleeding Edge)
**Kernel Target:** 6.13+ (Estimated)
**Strategy:** Rolling Re-provision (Wipe & Reload)
**Author:** Opencode Agent

## 1. Executive Summary
This document outlines the strategy to upgrade all 10 nodes in the Homelab cluster from **Fedora 39** to **Fedora 43**.

**Strategic Shift:**
Due to the high risk of cross-version dependency conflicts (F39 → F43 is 4 versions apart), we have abandoned the "In-Place Upgrade" (`dnf system-upgrade`) approach.
**Selected Strategy: Rolling Re-provision.**
Each node will be drained, wiped, and re-provisioned via PXE with a fresh Fedora 43 image, then bootstrapped back into the cluster. This ensures a clean state and eliminates config drift.

## 2. Risk Assessment & Critical Path
*Consolidated findings from Risk Assessment (2026-01-30)*

### 2.1. Critical Risks
*   **Unsupported In-Place Upgrade (avoided):** Direct F39->F43 upgrade is unsupported and prone to breakage. Re-provisioning mitigates this entirely.
*   **Kernel 6.13+ Compatibility:** Fedora 43 runs Kernel 6.13.
    *   **NVIDIA Drivers:** High risk of build failure. Action: Cap CUDA repo to F42 (see Pre-Flight).
    *   **Cilium:** Requires v1.17.0+ for Kernel 6.13 support.
*   **Device Naming:** Network interfaces may change names (e.g., `eth0` -> `enp3s0`) on new kernel/OS, potentially breaking Ceph public/cluster networks.

### 2.2. Critical Constraints
*   **Emby (Sprigatito):** Hard-pinned. Upgrade last. Downtime unavoidable.
*   **Rook/Ceph:** Running v20 (Squid). Must verify OSDs mount correctly on new OS.

## 3. Infrastructure State
| Node | Role | Hardware | Critical Workloads | Upgrade Phase |
|------|------|----------|--------------------|---------------|
| **Cyndaquil** | Worker | Standard | None (Canary) | **Phase 1** |
| **Bulbasaur** | Control | Standard | Etcd, Control Plane | **Phase 2** |
| **Charmander** | Control | Standard | Etcd, Control Plane | **Phase 2** |
| **Squirtle** | Control | Standard | Etcd, Control Plane | **Phase 2** |
| **Pikachu** | Worker | Standard | Monitoring | **Phase 3** |
| **Chikorita** | Worker | Standard | None | **Phase 3** |
| **Growlithe** | Worker | Standard | None | **Phase 3** |
| **Totodile** | Worker | Standard | None | **Phase 3** |
| **Arcanine** | Worker | **RTX 3090** | Ollama, GPU Operator | **Phase 4** |
| **Sprigatito** | Worker | **GTX 1650** | **Emby (Pinned)** | **Phase 5** |

## 4. Pre-Flight Checklist (Phase 0)
*Before any node is touched, the cluster MUST be prepared.*

### 4.1. Infrastructure Protection
*   [ ] **Etcd Snapshot:** `k3s etcd-snapshot save`.
*   [ ] **ArgoCD Backup:** Export critical manifests.
*   [ ] **PXE Server Update:**
    *   Download Fedora 43 Server ISO/Netboot imgs.
    *   Update PXE menu configs.
    *   Test PXE boot on a VM if possible.

### 4.2. Mandatory Config Updates
*   [ ] **Upgrade Cilium to v1.17.0+** (Completed if not checked? Verify).
*   [ ] **Patch GPU Ansible Role**:
    *   **File:** `metal/roles/virtualization/tasks/gpu_install_drivers.yml`
    *   **Action:** Add logic to force `cuda_repo_version: 42` when `ansible_distribution_major_version > 42`.
*   [ ] **Verify Network Config:** Check `metal/roles/network` for interface name hardcoding. Prefer MAC-based or generic matching.

## 5. Execution Strategy: Rolling Re-provision
*Standard Procedure for ALL nodes.*

1.  **Drain:** `kubectl cordon <node> && kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --force`
2.  **Sanitize:**
    *   If Control Plane: `kubectl delete node <node>` (Remove old object to clear Etcd member list? Verify K3s auto-handling).
    *   *Note on Etcd:* For K3s, usually replacing a master requires specific etcd member removal commands. **Verify K3s Etcd replacement steps.**
3.  **Wipe & install:**
    *   Reboot node into PXE.
    *   Select "Install Fedora 43".
    *   Wipe OS disk (Keep Data drives for OSDs!).
4.  **Bootstrap:**
    *   Run Ansible `bootstrap.yml`.
    *   Verify Node joins cluster.
5.  **Restore:**
    *   Uncordon.
    *   Verify OSDs (if applicable).

## 6. Phased Rollout Plan

### Phase 1: The Canary (`cyndaquil`)
*Goal: Validate F43 fresh install + K3s + Cilium.*
1.  **Execute:** perform Standard Re-provision.
2.  **Validate:**
    *   OS Version: `cat /etc/os-release`
    *   K3s Agent Running.
    *   Rook OSD: Check if OSD pod starts and finds the raw disk.

### Phase 2: Control Plane (`bulbasaur`, `charmander`, `squirtle`)
*Goal: Replace Control Plane one by one.*
1.  **Order:** `bulbasaur` → (Wait for Healthy) → `charmander` → (Wait) → `squirtle`.
2.  **Critical:** Ensure Etcd member list is healthy (`k3s etcd-snapshot`) before wiping the next master.
3.  **Procedure:** Standard Re-provision.

### Phase 3: Worker Batch
*Goal: Throughput.*
1.  **Batch:** `pikachu` + `chikorita`, then `growlithe` + `totodile`.
2.  **Procedure:** Standard Re-provision.

### Phase 4: GPU Pilot (`arcanine`)
*Goal: Verify Nvidia Drivers on F43.*
1.  **Execute:** Standard Re-provision.
2.  **Verify:** `nvidia-smi` inside GPU operator pods. **If 6.13 breaks drivers, hold here.**

### Phase 5: Critical (`sprigatito`)
*Goal: Restore Emby.*
1.  **Execute:** Standard Re-provision.
2.  **Time:** Expect 20-30 mins downtime.

## 7. Contingency
*   **Boot Failure:** If F43 fails to boot, re-provision with **Fedora 41** (Safe Fallback) via PXE to restore capacity immediately.
*   **App Failure:** If Apps fail on new Kernel, rollback node to F41.
