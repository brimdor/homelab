# PHASE 1: TPLink Switch Initial Configuration
**Estimated Duration**: 45-90 minutes  
**Downtime Risk**: None (switch not yet in production)  
**Human Required**: ✅ Physical connection, web UI access

---

## Important Notes About This Switch

> [!NOTE]
> **This TPLink switch uses basic 802.1Q VLAN configuration:**
> - There are NO "Access/Trunk/General" port modes
> - There is NO "Management VLAN" setting
> - Configuration is done by setting **Tagged/Untagged/Not Member** per VLAN per port, plus **PVID**
> - **Switch management is ALWAYS on VLAN 1** (native VLAN) — the switch can only be accessed from ports that have VLAN 1 Untagged

---

## 1.1 Physical Setup

### Step-by-Step Instructions:

1. **Power on the TPLink switch**
   - [ ] **[HUMAN ACTION]** Connect power cable to TPLink switch
   - [ ] **[HUMAN ACTION]** Plug into power outlet near server rack
   - [ ] **[HUMAN ACTION]** Wait for boot sequence (LEDs will flash, then stabilize)
   - Expected boot time: 30-60 seconds

2. **Connect laptop directly to switch**
   - [ ] **[HUMAN ACTION]** Use an ethernet cable to connect laptop to TPLink switch **Port 1**
   - [ ] **[HUMAN ACTION]** Disconnect laptop from any other networks (WiFi off)

3. **Configure laptop static IP**
   
   **Linux:**
   ```bash
   # Find your ethernet interface name first
   ip link show
   
   # Common names: enp0s31f6, eno1, enp3s0
   # Replace <interface> with your actual interface name
   
   sudo ip addr flush dev <interface>
   sudo ip addr add 192.168.0.100/24 dev <interface>
   sudo ip link set <interface> up
   
   # Verify
   ip addr show <interface>
   ```
   
   **Windows:**
   ```
   1. Open Control Panel → Network and Sharing Center
   2. Click "Change adapter settings"
   3. Right-click Ethernet adapter → Properties
   4. Select "Internet Protocol Version 4 (TCP/IPv4)" → Properties
   5. Select "Use the following IP address"
      - IP address: 192.168.0.100
      - Subnet mask: 255.255.255.0
      - Default gateway: 192.168.0.1
   6. Click OK → Close
   ```

4. **Verify physical link**
   ```bash
   ping 192.168.0.1
   # Should receive responses if connected correctly
   ```

---

## 1.2 Initial Switch Access and Security

### Step-by-Step Instructions:

1. **Access switch web interface**
   - [ ] **[HUMAN ACTION]** Open browser and navigate to: `http://192.168.0.1`
   - Alternative URLs: `http://tplinklogin.net` or `http://192.168.0.254`

2. **Login with default credentials**
   ```
   Username: admin
   Password: admin
   ```

3. **IMMEDIATELY change admin password**
   - [ ] **[HUMAN ACTION]** Navigate to: `System` → `User Management`
   - [ ] **[HUMAN ACTION]** Change password to a strong password
   - [ ] **[HUMAN ACTION]** Document new password in password manager

4. **Update switch management IP**
   - [ ] **[HUMAN ACTION]** Navigate to: `System` → `System IP`
   - [ ] **[HUMAN ACTION]** Change IP settings:
     - IP Address: `10.0.0.2`
     - Subnet Mask: `255.255.255.0`
     - Default Gateway: `10.0.0.1`
   - [ ] **[HUMAN ACTION]** Click Save/Apply
   
   > [!CAUTION]
   > After changing switch IP, you will lose connection. Reconfigure your laptop to 10.0.0.100/24 to reconnect.

5. **Reconnect with new IP**
   ```bash
   sudo ip addr flush dev <interface>
   sudo ip addr add 10.0.0.100/24 dev <interface>
   ```
   - [ ] **[HUMAN ACTION]** Navigate to: `http://10.0.0.2`
   - [ ] **[HUMAN ACTION]** Login with new admin password

---

## 1.3 Create VLANs on TPLink Switch

### Step-by-Step Instructions:

1. **Navigate to VLAN configuration**
   - Path: `L2 Features` → `VLAN` → `802.1Q VLAN` → `VLAN Config`

2. **Create each VLAN**

   | VLAN ID | Name | Click Apply after each |
   |---------|------|------------------------|
   | 10 | Management | ✓ |
   | 20 | Cluster-Prod | ✓ |
   | 30 | Cluster-Extra | ✓ |
   | 40 | Storage | ✓ |
   | 50 | IoT-Wireless | ✓ |

3. **Verify all VLANs created**
   - Confirm VLANs 1, 10, 20, 30, 40, 50 all appear in the list

---

## 1.4 Configure LAG for OPNSense (Ports 23 & 24)

### Step-by-Step Instructions:

1. **Create LAG Group**
   - Navigate to: `L2 Features` → `Switching` → `LAG` → `Static LAG` (or LAG Config)
   - Create LAG1 with Ports 23, 24 — Mode: **Static** (not LACP)

2. **Configure LAG1 VLAN membership**
   
   For each VLAN, set LAG1 (Ports 23-24) status:

   | VLAN | LAG1 Status |
   |------|-------------|
   | 1 | **Untagged** |
   | 10 | **Tagged** |
   | 20 | **Tagged** |
   | 30 | **Tagged** |
   | 40 | **Tagged** |
   | 50 | **Tagged** |

3. **Set LAG1 PVID**
   - Navigate to: `VLAN` → `PVID Setting`
   - Set LAG1 PVID to: **1**

4. **Verification**
   - [ ] LAG1 created with Ports 23 and 24
   - [ ] VLAN 1: Untagged, VLANs 10/20/30/40/50: Tagged
   - [ ] PVID: 1

---

## 1.4b Configure LAG2 for NAS (Ports 19 & 20)

> [!IMPORTANT]
> The NAS uses a bonded interface (br0). Both switch ports MUST be in a LAG to avoid MAC flapping.

### Step-by-Step Instructions:

1. **Create LAG2 Group**
   - Navigate to: `L2 Features` → `Switching` → `LAG` → `Static LAG`
   - Create LAG2 with Ports 19, 20 — Mode: **Static**

2. **Configure LAG2 VLAN membership**

   | VLAN | LAG2 Status |
   |------|-------------|
   | 1 | **Not Member** |
   | 10 | **Not Member** |
   | 20 | **Not Member** |
   | 30 | **Not Member** |
   | 40 | **Untagged** |
   | 50 | **Not Member** |

3. **Set LAG2 PVID**
   - Navigate to: `VLAN` → `PVID Setting`
   - Set LAG2 PVID to: **40**

4. **Verification**
   - [ ] LAG2 created with Ports 19 and 20
   - [ ] VLAN 40: Untagged, all others: Not Member
   - [ ] PVID: 40


## 1.5 Configure Port 22 for WiFi AP

| VLAN | Port 22 Status |
|------|----------------|
| 1 | **Not Member** |
| 10 | **Tagged** |
| 20 | **Not Member** |
| 30 | **Not Member** |
| 40 | **Not Member** |
| 50 | **Untagged** |

**PVID**: 50

---

## 1.6 Configure Access Ports for Devices

### Port 1 — STAYS ON VLAN 1 (Management Access)

> [!IMPORTANT]
> **Port 1 must remain on VLAN 1** so you can always access the switch management interface. The switch has NO Management VLAN setting — it's only accessible from VLAN 1 ports.

| VLAN | Port 1 Status |
|------|---------------|
| 1 | **Untagged** |
| 10-50 | **Not Member** |

**PVID**: 1

---

### Ports 2-11 — Kubernetes Production (VLAN 20)

| VLAN | Ports 2-11 Status |
|------|-------------------|
| 1 | **Not Member** |
| 10 | **Not Member** |
| 20 | **Untagged** |
| 30 | **Not Member** |
| 40 | **Not Member** |
| 50 | **Not Member** |

**PVID**: 20

---

### Ports 12-18 — Raspberry Pi Cluster (VLAN 30)

| VLAN | Ports 12-18 Status |
|------|-------------------|
| 1 | **Not Member** |
| 10 | **Not Member** |
| 20 | **Not Member** |
| 30 | **Untagged** |
| 40 | **Not Member** |
| 50 | **Not Member** |

**PVID**: 30

---

### Ports 19-20 — NAS/Storage (VLAN 40) — LAG2

> [!NOTE]
> Ports 19-20 are configured as LAG2 (see section 1.4b). Configure the LAG, not individual ports.

| VLAN | LAG2 Status |
|------|-------------|
| 1 | **Not Member** |
| 10 | **Not Member** |
| 20 | **Not Member** |
| 30 | **Not Member** |
| 40 | **Untagged** |
| 50 | **Not Member** |

**PVID**: 40

---


### Port 21 — IoT Devices (VLAN 50)

| VLAN | Port 21 Status |
|------|----------------|
| 1 | **Not Member** |
| 10 | **Not Member** |
| 20 | **Not Member** |
| 30 | **Not Member** |
| 40 | **Not Member** |
| 50 | **Untagged** |

**PVID**: 50

---

## 1.7 Save and Backup Configuration

1. **Save running configuration**
   - Navigate to: `System` → `System Tools` → `Config Restore/Backup`
   - Click "Save" to save running config to startup config

2. **Export configuration backup**
   - Click "Backup" or "Export"
   - Save as: `tplink-switch-config-2025-12-13.cfg`

3. **Verify configuration persists**
   - Power cycle the switch
   - Login and verify all settings are intact

---

## Phase 1 Checkpoint

> [!IMPORTANT]
> **Before proceeding to Phase 2, verify:**
>
> - [ ] All VLANs exist (1, 10, 20, 30, 40, 50)
> - [ ] Switch management IP is `10.0.0.2` (on VLAN 1 subnet)
> - [ ] LAG1 (Ports 23-24): VLAN 1 Untagged, VLANs 10-50 Tagged, PVID 1
> - [ ] Port 22 (AP): VLAN 10 Tagged, VLAN 50 Untagged, PVID 50
> - [ ] Port 1: VLAN 1 Untagged, PVID 1 (for switch management access)
> - [ ] Ports 2-21: Configured per VLAN assignments above
> - [ ] Configuration saved and backed up

---

## Port Summary Table

| Port(s) | VLAN | PVID | Purpose |
|---------|------|------|---------|
| 1 | 1 (Untagged) | 1 | **Switch Management Access** |
| 2-11 | 20 (Untagged) | 20 | Kubernetes Production |
| 12-18 | 30 (Untagged) | 30 | Raspberry Pi Cluster |
| 19-20 | 40 (Untagged) | 40 | NAS/Storage (2 ports) |
| 21 | 50 (Untagged) | 50 | IoT Devices |
| 22 | 10T, 50U | 50 | WiFi AP Trunk |
| 23-24 (LAG1) | 1U, 10T, 20T, 30T, 40T, 50T | 1 | OPNSense Trunk |

**Legend**: U = Untagged, T = Tagged
