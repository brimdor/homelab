# 🚀 Homelab Fedora 43 Upgrade Strategy & Pre-Mortem

**Version:** 2.1.0
**Date:** 2026-01-30
**Target OS:** Fedora Linux 43 (Stable)
**Kernel Target:** 6.17+ (Confirmed)
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
    *   **NVIDIA Drivers (Critical):** High risk of build failure on Kernel 6.17+.
        *   *Mitigation:* Cap CUDA repo to F41/F42. Be prepared to hold `arcanine` on F39 or F41 if drivers fail to build.
    *   **Cilium (BLOCKER):** **Current version v1.15.1 is INCOMPATIBLE.** Kernel 6.17 requires **Cilium v1.17.1+**.
        *   *Action:* Must upgrade Cilium to latest stable (1.17.1+) BEFORE any node touches F43.
*   **DNF5 Transition (Medium):** Fedora 43 uses DNF5 by default.
    *   *Impact:* Potential Ansible `dnf` module incompatibilities or CLI syntax changes in shell tasks.
    *   *Mitigation:* Audit all `shell: dnf` tasks. Ensure Ansible is updated.
*   **Python 3.14 (Medium):** F43 ships Python 3.14.
    *   *Impact:* Ansible controller might need `python3-dnf` or compatible bindings on the target.
*   **Device Naming (High):** Network interfaces WILL likely change names (e.g., `eth0` -> `enp3s0`) due to systemd/udev changes in 4 major versions.
    *   *Impact:* Broken connectivity if Ansible network roles use hardcoded names.
    *   *Mitigation:* Verify `metal/roles` use compatible networking configs (NetworkManager).

### 2.2. Critical Constraints
*   **Emby (Sprigatito):** Hard-pinned. Upgrade last. Downtime unavoidable.
*   **Rook/Ceph:** Running v20 (Squid). OSDs are robust, but device path changes (`/dev/sdX` vs `/dev/disk/by-id`) could confuse Ceph if not using LVM batch/persistent naming.

### 2.3. Release Note Audit (F40 -> F43)
*Exhaustive audit from Fedora release notes - 2026-01-30*

#### Fedora 40 Changes
| Item | Severity | Status | Impact |
|------|----------|--------|--------|
| **Podman 5** | Medium | ⚠️ Verify | Mandatory cgroups v2 & netavark. CNI deprecated. |
| **Wget2 as wget** | Low | ⚠️ Verify | `wget` is now `wget2`. Check scripts. |
| **Wi-Fi MAC stable-ssid** | Medium | ⚠️ Action | Wireless nodes need `wifi.cloned-mac-address=permanent`. |
| 389-DS LMDB default | Info | N/A | K3s doesn't use 389-DS. |
| SSSD files provider removed | Low | ⚠️ Check | May affect local user auth if SSSD configured. |
| Authselect minimal→local | Low | ⚠️ Check | Ansible scripts may reference `minimal` profile. |
| DNF filelists not downloaded | Low | ⚠️ Check | May affect `dnf provides` queries in scripts. |
| Java 21 system JDK | Medium | ⚠️ Verify | If bare metal Java apps exist, verify JDK compat. |

#### Fedora 41 Changes (CRITICAL)
| Item | Severity | Status | Impact |
|------|----------|--------|--------|
| **DNF5 default** | High | ⚠️ Action | CLI syntax changes, Ansible `dnf` module behavior. |
| **Kubernetes versioned RPMs** | **BLOCKER** | ⚠️ Action | `kubernetes-client` → `kubernetes1.XX-client`. |
| **ifcfg REMOVED from NM** | **HIGH** | ⚠️ Action | Legacy ifcfg network configs will **BREAK**. |
| **network-scripts REMOVED** | **HIGH** | ⚠️ Action | `ifup`/`ifdown` commands **GONE**. |
| **Libvirt nftables backend** | Medium | ⚠️ Check | May impact VM networking if using custom iptables. |
| **Netavark nftables default** | Medium | ⚠️ Check | Podman firewall rules now use nftables. |
| **OpenSSL SHA-1 distrusted** | Medium | ⚠️ Verify | May break legacy TLS certs. |
| **Redis → Valkey** | Medium | ✅ K8s | Handled by K8s deployments. |
| Consistent device naming | **HIGH** | ⚠️ Verify | `net.ifnames=0` removed. Interface names WILL change. |
| TuneD replaces PPD | Low | Info | Power-profiles-daemon replaced on desktops. |
| Python 2 retired | Medium | ⚠️ Check | No Python 2 scripts allowed. |
| `sss_ssh_knownhostsproxy` removed | Low | ⚠️ Check | Use `sss_ssh_knownhosts` instead. |

#### Fedora 42 Changes (CRITICAL)
| Item | Severity | Status | Impact |
|------|----------|--------|--------|
| **Anaconda WebUI default** | Medium | ⚠️ PXE | PXE installer UI is different. |
| **VNC REMOVED from Anaconda** | **BLOCKER** | ⚠️ Action | **TigerVNC BROKEN**. Must use RDP (`inst.rdp`). |
| Legacy JDKs retired (8,11,17) | **HIGH** | ⚠️ Action | Use `adoptium-temurin-java-repository` if needed. |
| Intel Compute pre-2020 dropped | Medium | ✅ Noted | Gen 12 and older iGPUs lose compute support. |
| **`/usr/sbin` → symlink** | Medium | ⚠️ Audit | `/usr/sbin` is symlink to `/usr/bin`. |
| **Ansible 11** | **HIGH** | ⚠️ Action | Dropped Python 3.10 controller, Python 3.7 target. |
| Plymouth simpledrm | Low | Info | Boot splash may scale differently. |
| `fips-mode-setup` removed | Low | ⚠️ Check | Use `fips=1` kernel arg instead. |
| cockpit-files replaces navigator | Low | Info | Cockpit UI change. |
| GPT default all architectures | Info | N/A | Already using GPT. |
| NumPy 2 | Medium | ⚠️ Check | Python ML scripts may need updates. |
| PostgreSQL 15 retired | Medium | ⚠️ Check | PG 16 or 17 required. |

#### Fedora 43 Changes (CRITICAL)
| Item | Severity | Status | Impact |
|------|----------|--------|--------|
| **Python 3.14** | **HIGH** | ⚠️ Verify | Ansible/Python bindings must be ready. |
| **Default /boot is 2G** | **HIGH** | ⚠️ Verify | Fresh installs allocate 2G to /boot. |
| **RPM 6.0** | Medium | ⚠️ Verify | OpenPGP key fingerprint handling changed. |
| **Java 25 / No default JDK** | **HIGH** | ⚠️ Action | Must choose Java version with `alternatives`. |
| **Tomcat 10.1** | **BLOCKER** | ⚠️ Verify | `javax.*` → `jakarta.*` namespace **BREAKING**. |
| GNOME X11 removed | Medium | Info | Wayland only for GNOME. |
| initrd zstd compression | Low | ⚠️ Check | Custom dracut configs may need updates. |
| 389-DS BerkeleyDB removed | Low | ⚠️ Check | Migrate to LMDB if using 389-DS. |
| PostgreSQL 18 | Medium | ⚠️ Check | Major PG version jump. |
| MySQL 8.4 default | Medium | ⚠️ Check | If MySQL used. |
| Dovecot 2.4 | Low | ⚠️ Check | If running bare-metal mail. |
| GnuPG2 modular packaging | Low | Info | `gnupg2-utils` now separate. |
| Modularity removed from Anaconda | Medium | ⚠️ Note | Modular repos don't work in F43 installer. |
| GNU Toolchain (gcc 15.2, glibc 2.42) | Medium | Info | Major toolchain bump. |
| Gold linker deprecated | Low | Info | Use ld.bfd, lld, or mold. |

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

#### 🚨 CRITICAL BLOCKERS (Must Complete Before ANY Node)

*   [ ] **Upgrade Cilium to v1.17.1+**
    *   **Current:** v1.15.1 (Found in `metal/roles/cilium/defaults/main.yml`)
    *   **Action:** Update Ansible role variable `cilium_version` to `1.17.1` and run playbook. **Do not proceed until stable.**

*   [ ] **Update PXE for RDP (VNC Removed in F42)**
    *   **Issue:** Anaconda is now a Wayland app. TigerVNC depends on X11 and **cannot be used**.
    *   **Boot Options Changed:**
        *   ❌ Removed: `inst.vnc`, `inst.vncpassword`, `inst.vncconnect`
        *   ✅ New: `inst.rdp`, `inst.rdp.username`, `inst.rdp.password`
    *   **Action:** Update PXE boot config to use RDP for remote graphical install.
    *   **Verify:** Test RDP connection to installer on canary node.

*   [ ] **Verify Ansible 11 Compatibility**
    *   **Issue:** F42 ships Ansible 11 / ansible-core 2.18.
    *   **Controller:** Requires Python 3.11+ (Dropped 3.10)
    *   **Targets:** Requires Python 3.8+ (Dropped 3.7)
    *   **Action:** Run `ansible --version` on controller, verify playbooks compatible.

#### ⚠️ HIGH PRIORITY (Must Verify/Fix Before Proceeding)

*   [ ] **Audit ifcfg and network-scripts Usage (F41)**
    *   **Issue:** ifcfg format REMOVED from NetworkManager. `ifup`/`ifdown` commands GONE.
    *   **Impact:** Legacy network configs will **BREAK**.
    *   **Action:** Verify all network configs use NetworkManager keyfile format.
    *   **Check:** `ls /etc/sysconfig/network-scripts/` - should be empty or not exist.

*   [ ] **Fix Kubernetes Package Names (F41+)**
    *   **Issue:** F41 splits `kubernetes-client` into `kubernetes1.XX-client`.
    *   **Action:** Update Ansible `kubectl` installation task to detect OS version or pin specific package name.

*   [ ] **Patch GPU Ansible Role**
    *   **File:** `metal/roles/virtualization/tasks/gpu_install_drivers.yml`
    *   **Action:** Add logic to force `cuda_repo_version: 41` (Safe) when `ansible_distribution_major_version >= 43` (until F43 repo is proven/stable).
    *   **Verify:** Run `curl -I` validation for the chosen repo version during the run.

*   [ ] **Verify /boot Partition Size (F43)**
    *   **Issue:** F43 default /boot is now 2G.
    *   **Action:** Check PXE kickstart allocates adequate /boot space.
    *   **Verify:** `df -h /boot` on existing nodes - ensure sufficient space.

*   [ ] **Java Version Strategy (F43)**
    *   **Issue:** No default system JDK. Java 21 still available but Java 25 is new.
    *   **Action:** If Java needed, add post-bootstrap step: `alternatives --config java`.
    *   **Tomcat Warning:** If running Tomcat apps, `javax.*` → `jakarta.*` namespace is BREAKING.

#### 📋 MEDIUM PRIORITY (Verify Before Each Phase)

*   [ ] **Audit Network Config**
    *   Check `metal` roles. Ensure we don't rely on `eth0`.
    *   *Tip:* If nodes fail to come online, check if interface name changed and update inventory/DNS/DHCP if strictly mapped.

*   [ ] **Audit `/usr/sbin` Paths (F42)**
    *   **Issue:** `/usr/sbin` is now symlink to `/usr/bin`.
    *   **Action:** Audit Ansible roles for explicit `/usr/sbin/` paths.

*   [ ] **Audit Python 2 Usage (F41)**
    *   **Issue:** Python 2 completely retired.
    *   **Action:** Verify no Python 2 scripts or dependencies.

*   [ ] **Verify DNF5 CLI Compatibility**
    *   **Issue:** DNF5 syntax differs slightly from DNF4.
    *   **Action:** Audit Ansible `shell: dnf` tasks for syntax changes.

*   [ ] **Python 3.14 Readiness (F43)**
    *   **Action:** Ensure Ansible controller is running latest stable Ansible to support Python 3.14 targets.

*   [ ] **Audit Java Workloads (F42)**
    *   **Issue:** Legacy JDKs (8, 11, 17) removed in F42.
    *   **Action:** If running Jenkins/Elasticsearch on bare metal, add Adoptium repo.

*   [ ] **Verify nftables Compatibility**
    *   **Issue:** Libvirt (F41) and Netavark/Podman (F41+) now use nftables.
    *   **Action:** Verify no iptables-specific rules in custom networking.

#### ℹ️ LOW PRIORITY (Informational)

*   [ ] **Wi-Fi MAC Persistence (F40)**
    *   **Action:** If `cyndaquil` or `sprigatito` use Wi-Fi, set `wifi.cloned-mac-address=permanent` in NM connection profile to avoid DHCP IP changes.

*   [ ] **Note: Plymouth simpledrm (F42)**
    *   Boot splash may use different scaling. Override with `plymouth.force-scale=1` if needed.

*   [ ] **Note: initrd zstd compression (F43)**
    *   Custom dracut configs may need updates if using xz-specific options.

*   [ ] **Note: Cockpit UI Change (F42)**
    *   cockpit-files replaces cockpit-navigator. File browser now under "Tools".

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

#### 1. Execution
1.  **Execute:** Standard Re-provision.

#### 2. Success Criteria (GATE)
**The node MUST be "All Green" to proceed. NO EXCEPTIONS.**
*   **System:** Node is `Ready`. All `kube-system` pods are `Running`.
*   **Storage:** Local Rook OSD is `up` and `in`. Ceph Health is `HEALTH_OK`.
*   **Network:** Cilium connectivity check passes.
*   **Logs:** No critical hardware/kernel errors in `dmesg`.
*   **Verdict:** If ANY check fails, proceed to **Rollback**.

#### 3. Phase 1 Failure & Rollback Protocol
**Trigger:** If Success Criteria are NOT met within 60 minutes or critical blockers are found.
1.  **HALT:** The upgrade project is PAUSED.
2.  **ROLLBACK:** Re-provision `cyndaquil` immediately via PXE with **Fedora 39** (Original State) to restore capacity.
3.  **VERIFY:** Ensure `cyndaquil` rejoins the cluster and returns to Green status.
4.  **REPORT (Mandatory):**
    *   Generate an **Exhaustive Incident Report** detailing:
        *   Exact failure mode (kernel panic, driver failure, pod crash).
        *   Logs (`dmesg`, `journalctl`, pod logs).
        *   Root cause analysis.
    *   *Note:* No further nodes will be touched until the report is reviewed and the plan amended.

### Phase 2: Control Plane (`bulbasaur`, `charmander`, `squirtle`)
*Goal: Replace Control Plane one by one while maintaining quorum.*

#### 1. Execution
1.  **Order:** `bulbasaur` → (Wait for Healthy) → `charmander` → (Wait for Healthy) → `squirtle`.
2.  **Critical:** Ensure Etcd member list is healthy (`k3s etcd-snapshot`) before wiping the next master.
3.  **Procedure:** Standard Re-provision.

#### 2. Success Criteria (GATE)
**Proceed to the next node ONLY if current node is "All Green".**
*   **Cluster:** Etcd cluster health is `healthy` (3 members).
*   **System:** Node is `Ready` and joined as control-plane.
*   **Storage:** Local rook OSD is `up` and `in`.
*   **Verdict:** If ANY check fails, **STOP**. Do not modify the next node.

#### 3. Phase 2 Failure & Rollback Protocol
**Trigger:** Etcd issues or Node fails to join.
1.  **HALT:** Stop all work immediately.
2.  **ROLLBACK NODE:** Re-provision the failed node with **Fedora 39** to restore previous state.
3.  **ETCD RECOVERY (If Quorum Lost):**
    *   If 2+ masters are down/broken: Stop K3s on remaining master.
    *   Restore from `pre-upgrade-snapshot` taken in Phase 0.
    *   Force start K3s on remaining master.
    *   Join reinstated masters one by one.

### Phase 3: Worker Batch
*Goal: Throughput update of standard workers.*

#### 1. Execution
1.  **Batch:** `pikachu` + `chikorita`, then `growlithe` + `totodile`.
2.  **Procedure:** Standard Re-provision.

#### 2. Success Criteria (GATE)
*   **System:** All re-provisioned nodes are `Ready`.
*   **Storage:** All OSDs on these nodes are `up` and `in`.
*   **Workloads:** Pods scheduled on these nodes are `Running`.

#### 3. Phase 3 Failure & Rollback Protocol
**Trigger:** Batch failure or mass pod crash.
1.  **ROLLBACK:** Re-provision failed nodes with **Fedora 39**.
2.  **ISOLATE:** If only one node fails, cordon it and proceed with others (optional), or pause to investigate.

### Phase 4: GPU Pilot (`arcanine`)
*Goal: Verify Nvidia Drivers and AI workloads on F43.*

#### 1. Execution
1.  **Execute:** Standard Re-provision.
2.  **Verify:** `nvidia-smi` inside GPU operator pods.

#### 2. Success Criteria (GATE)
*   **Drivers:** `nvidia-smi` returns valid GPU status (not error).
*   **Workloads:** Ollama serves requests successfully.
*   **System:** Node `Ready`, no kernel tainting issues.

#### 3. Phase 4 Failure & Rollback Protocol
**Trigger:** Driver build failure or GPU instability on Kernel 6.13+.
1.  **ROLLBACK STRATEGY A (Driver Fix):** Re-provision with **Fedora 41** (Known compat) if F43 driver build fails.
2.  **ROLLBACK STRATEGY B (Full Retreat):** Re-provision with **Fedora 39** if F41 also fails or is unstable.

### Phase 5: Critical (`sprigatito`)
*Goal: Restore Emby and media services.*

#### 1. Execution
1.  **Execute:** Standard Re-provision.
2.  **Time:** Expect 20-30 mins downtime.

#### 2. Success Criteria (GATE)
*   **App:** Emby web interface is accessible.
*   **Storage:** Media mounts are accessible/rw.
*   **Hardware:** Transcoding works (if node specific hardware utilized).

#### 3. Phase 5 Failure & Rollback Protocol
**Trigger:** Emby fails to start or mount storage.
1.  **ROLLBACK:** Re-provision with **Fedora 39** immediately to restore service.

## 8. Project Success & Global Rollback

### 8.1. Final Success Criteria
**The project is complete ONLY when:**
1.  **Uniformity:** All 10/10 nodes are running **Fedora 43**.
2.  **Health:** All layers (Metal, System, Platform, Apps) are **GREEN**.
    *   No `NotReady` nodes.
    *   No `Degraded` ArgoCD apps.
    *   No `CrashLoopBackOff` pods related to upgrade.
    *   Ceph is `HEALTH_OK`.
3.  **Documentation:** Inventory and documentation updated to reflect F43.

### 8.2. Global Rollback Plan (The "Red Button")
**Trigger:** Catastrophic failure affecting data integrity or inability to operate cluster on F43.

1.  **ASSESS:** Functioning on mixed versions (e.g., F39/F43 hybrid) is preferred over a broken cluster.
2.  **PARTIAL RETREAT:** If a specific component (e.g., Ceph) hates F43, rollback ALL nodes to **Fedora 39**.
    *   This is a massive undertaking (10x re-provisions).
    *   Only done if data is at risk.
3.  **DISASTER RECOVERY:**
    *   If Config/Data is corrupted:
    *   Restore manifests from Git (ArgoCD).
    *   Restore PVC data from external backups (Velero/Restic if available).
    *   Restore Etcd from Snapshot.


