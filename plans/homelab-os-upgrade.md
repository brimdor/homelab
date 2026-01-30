# 🚀 Homelab Fedora 43 Upgrade Strategy & Pre-Mortem

**Version:** 2.1.0
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

## 2. Risk Assessment & Pre-Mortem Analysis
*Consolidated findings from Pre-Mortem Analysis (2026-01-30)*

### 2.1. Critical Risks
*   **Unsupported In-Place Upgrade (avoided):** Direct F39->F43 upgrade is unsupported and prone to breakage. Re-provisioning mitigates this entirely.
*   **Kernel 6.13+ Compatibility:** Fedora 43 runs Kernel 6.13.
    *   **NVIDIA Drivers (Critical):** High risk of build failure on bleeding edge kernels.
        *   *Mitigation:* Cap CUDA repo to F41/F42. Be prepared to hold `arcanine` on F39 if drivers fail to build.
    *   **Cilium (BLOCKER):** **Current version v1.15.1 is INCOMPATIBLE.** Kernel 6.13 requires **Cilium v1.17.0+**.
        *   *Action:* Must upgrade Cilium BEFORE any node touches F43.
*   **Device Naming (High):** Network interfaces WILL likely change names (e.g., `eth0` -> `enp3s0`) due to systemd/udev changes in 4 major versions.
    *   *Impact:* Broken connectivity if Ansible network roles use hardcoded names.
    *   *Mitigation:* Verify `metal/roles` use compatible networking configs (NetworkManager).

### 2.2. Critical Constraints
*   **Emby (Sprigatito):** Hard-pinned. Upgrade last. Downtime unavoidable.
*   **Rook/Ceph:** Running v20 (Squid). OSDs are robust, but device path changes (`/dev/sdX` vs `/dev/disk/by-id`) could confuse Ceph if not using LVM batch/persistent naming.

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
| **Arcanine** | Worker | **RTX 3090** | Ollama, GPU Operator | **Phase 4 (Risk)**|
| **Sprigatito** | Worker | **GTX 1650** | **Emby (Pinned)** | **Phase 5** |

## 4. Pre-Flight Checklist (Phase 0)
*Before any node is touched, the cluster MUST be prepared.*

### 4.1. Infrastructure Protection
*   [ ] **Etcd Snapshot:** `k3s etcd-snapshot save --name pre-upgrade-snapshot`.
*   [ ] **ArgoCD Backup:** Export critical manifests.
*   [ ] **PXE Server Update:**
    *   Download Fedora 43 Server ISO/Netboot imgs.
    *   Update PXE menu configs.
    *   Test PXE boot on a VM if possible.

### 4.2. Mandatory Config Updates (BLOCKERS)
*   [ ] **Upgrade Cilium to v1.17.1+**
    *   **Current:** v1.15.1 (Found in `metal/roles/cilium/defaults/main.yml`)
    *   **Action:** Update Ansible role variable `cilium_version` to `1.17.1` and run playbook. **Do not proceed until stable.**
*   [ ] **Patch GPU Ansible Role**:
    *   **File:** `metal/roles/virtualization/tasks/gpu_install_drivers.yml`
    *   **Action:** Add logic to force `cuda_repo_version: 41` (Safe) when `ansible_distribution_major_version > 41`.
*   [ ] **Audit Network Config:**
    *   Check `metal` roles. Ensure we don't rely on `eth0`.
    *   *Tip:* If nodes fail to come online, check if interface name changed and update inventory/DNS/DHCP if strictly mapped.

## 5. Execution Strategy: Rolling Re-provision
*Standard Procedure for ALL nodes.*

1.  **Drain:** `kubectl cordon <node> && kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --force`
2.  **Sanitize:**
    *   *Control Plane:* `kubectl delete node <node>` (Required for Etcd member removal on K3s to trigger re-join as new member).
    *   *Workers:* Delete node object to clear heavy states.
3.  **Wipe & install:**
    *   Reboot node into PXE.
    *   Select "Install Fedora 43".
    *   **CRITICAL:** Wipe OS disk (NVMe/SSD). **PROTECT OSD DRIVES (SATA/Spinners).**
4.  **Bootstrap:**
    *   Run Ansible `bootstrap.yml`.
    *   Monitor for network interface name changes during first boot.
5.  **Restore:**
    *   Verify Node Ready.
    *   Uncordon.
    *   **Ceph Check:** `kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph status` -> HEALTH_OK?

## 6. Phased Rollout Plan

### Phase 1: The Canary (`cyndaquil`)
*Goal: Validate F43 fresh install + K3s + Cilium.*
1.  **Execute:** Standard Re-provision.
2.  **Validate:**
    *   **Kernel:** `uname -r` (Expect 6.13+)
    *   **Cilium:** Pods Running? (If `CrashLoopBackOff`, check kernel logs for BPF errors).
    *   **Rook OSD:** Check if OSD pod starts and finds the raw disk.

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
2.  **Verify:** `nvidia-smi` inside GPU operator pods. **If 6.13 breaks drivers, rollback to F41.**

### Phase 5: Critical (`sprigatito`)
*Goal: Restore Emby.*
1.  **Execute:** Standard Re-provision.
2.  **Time:** Expect 20-30 mins downtime.

## 7. Contingency
*   **Boot Failure:** If F43 fails to boot, re-provision with **Fedora 41** (Safe Fallback) via PXE to restore capacity immediately.
*   **App Failure:** If Apps fail on new Kernel, rollback node to F41.
*   **Cilium Failure:** If Cilium cannot run on 6.13 even with upgrade, **ABORT UPGRADE**. Rollback to F39/F41.
