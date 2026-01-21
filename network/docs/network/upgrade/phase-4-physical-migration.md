# PHASE 4: Physical Migration (Rolling Transition)
**Estimated Duration**: 2-4 hours  
**Downtime Risk**: Moderate (per-device, not full network)  
**Human Required**: ✅ Physical cable management

> [!CAUTION]
> **Migration Order is Critical**: Migrate in the order below to maintain network stability and Twingate connectivity.

---

## Migration Strategy Overview

The migration follows a "critical-first" approach to maintain remote access and cluster stability:

1. **OPNSense → TPLink connection first** - Enables VLAN routing
2. **Twingate/NAS second** - Ensures remote access remains available
3. **Kubernetes controller third** - Maintains cluster control
4. **Kubernetes workers** - Rolling migration to minimize service disruption
5. **Secondary devices** - Raspberry Pis and extras last
6. **Wireless AP** - After all wired devices

---

## 4.1 Connect OPNSense to TPLink Switch

### Step-by-Step Instructions:

> [!IMPORTANT]
> This is the pivotal step that enables VLAN routing. After this, VLANs become active.

1. **Prepare the connection**
   - [ ] **[HUMAN ACTION]** Locate an ethernet cable (Cat5e or better)
   - [ ] **[HUMAN ACTION]** Identify OPNSense LAN port (eth1 - should be labeled or documented)
   - [ ] **[HUMAN ACTION]** Identify TPLink Switch Port 24 (trunk port)

2. **Make the connection**
   - [ ] **[HUMAN ACTION]** Unplug OPNSense LAN cables from Linksys switch (if connected)
   - [ ] **[HUMAN ACTION]** Connect OPNSense LAN port (eth1) to TPLink Switch **Port 23**
   - [ ] **[HUMAN ACTION]** Connect OPNSense LAN port (eth2) to TPLink Switch **Port 24**
   - [ ] **[HUMAN ACTION]** Verify link LED lights up on both devices for both cables

3. **Verify OPNSense routing works**
   - From a device still connected to Linksys OR from OPNSense console:
   ```bash
   # Test basic connectivity
   ping 10.0.0.1    # Should respond (OPNSense itself)
   
   # Test VLAN interfaces are up
   # In OPNSense: Interfaces → Overview
   # All VLAN interfaces should show "up"
   ```

4. **Connect a test device to TPLink**
   - [ ] **[HUMAN ACTION]** Connect laptop to TPLink Port 3 (VLAN 20) temporarily
   - Run tests:
   ```bash
   # Check IP assignment
   ip addr  # Should get 10.0.20.x IP
   
   # Test gateway
   ping 10.0.20.1   # OPNSense VLAN 20 gateway
   
   # Test internet
   ping 8.8.8.8
   curl -I https://google.com
   ```
   - [ ] Test device confirmed working on VLAN 20

---

## 4.2 Migrate UNRAID NAS (Twingate Critical)

### Step-by-Step Instructions:

> [!CAUTION]
> **Before this step**: Ensure you have local console access to UNRAID (monitor + keyboard or IPMI) in case network fails. This is your safety net.

1. **Pre-migration verification**
   - [ ] **[HUMAN ACTION]** Confirm UNRAID console access is available
   - [ ] **[HUMAN ACTION]** Open Twingate admin console in a browser (https://admin.twingate.com)
   - [ ] **[HUMAN ACTION]** Have a remote device ready to test Twingate

2. **Perform the migration**
   - [ ] **[HUMAN ACTION]** Locate UNRAID's network cables at the Linksys switch
   - [ ] **[HUMAN ACTION]** Unplug both UNRAID network cables from Linksys
   - [ ] **[HUMAN ACTION]** **Verify Unraid Bonding Mode**: Set to **Mode 2 (balance-xor)** (Recommended) or Mode 0.
   - [ ] **[HUMAN ACTION]** Immediately plug NAS Port 1 into TPLink **Port 19** (LAG2 Member)


   - [ ] **[HUMAN ACTION]** Immediately plug NAS Port 2 into TPLink **Port 20** (LAG2 Member)
   - Note the time: _________

3. **Wait for DHCP lease**
   - Expected wait time: 10-60 seconds
   - UNRAID should obtain IP: 10.0.40.3 (from static mapping created in Phase 2)

4. **Verify UNRAID network**
   - From UNRAID console or web UI:
   ```bash
   # Check IP address
   ip addr show eth0  # Should show 10.0.40.3
   
   # Verify gateway
   ip route           # Default gateway should be 10.0.40.1
   
   # Test internet connectivity
   ping 8.8.8.8
   ```

5. **TEST TWINGATE IMMEDIATELY**
   - [ ] **[HUMAN ACTION]** From a REMOTE location (phone on cellular, external machine):
     1. Open Twingate client
     2. Click on any "Geek Network" resource
     3. Verify you can connect
   - [ ] **[HUMAN ACTION]** Check Twingate admin console - connector should show "Online"

6. **If Twingate fails - ROLLBACK**
   ```
   ⚠️ ROLLBACK PROCEDURE:
   1. Immediately unplug UNRAID from TPLink
   2. Plug UNRAID back into Linksys switch
   3. Wait for IP (old IP will be assigned)
   4. Verify Twingate reconnects
   5. STOP migration and troubleshoot firewall/VLAN config
   ```

- [ ] UNRAID migrated successfully
- [ ] Twingate verified working from remote location

---

## 4.3 Migrate Kubernetes Controller (ash)

### Step-by-Step Instructions:

1. **Pre-migration check**
   ```bash
   # Verify current cluster state
   kubectl get nodes -o wide
   
   # ash should show current IP 10.0.20.10 and "Ready" status
   ```

2. **Perform the migration**
   - [ ] **[HUMAN ACTION]** Locate ash's network cable at Linksys switch
   - [ ] **[HUMAN ACTION]** Unplug ash from Linksys
   - [ ] **[HUMAN ACTION]** Plug ash into TPLink Switch **Port 2** (VLAN 20)
   - Note the time: _________

3. **Wait for node to obtain new IP**
   - Expected wait: 30-90 seconds (DHCP + Kubernetes reconciliation)
   - New IP should be: 10.0.20.10 (from static mapping)

4. **Update kubeconfig with new IP**
   ```bash
   # Edit ~/.kube/config
   # Change server URL from old IP to new:
   # OLD: server: https://10.0.20.10:6443
   # NEW: server: https://10.0.20.10:6443
   ```

5. **Verify Kubernetes API**
   ```bash
   # Try multiple times - may take a moment to stabilize
   kubectl get nodes -o wide
   
   # ash should now show 10.0.20.10 IP
   # Status should be "Ready" (may briefly show "NotReady")
   ```

6. **If controller fails - ROLLBACK**
   ```
   ⚠️ ROLLBACK PROCEDURE:
   1. Unplug ash from TPLink
   2. Plug ash back into Linksys
   3. Revert kubeconfig to old IP
   4. Wait for cluster to stabilize
   5. Investigate VLAN/DHCP configuration
   ```

- [ ] ash (controller) migrated to 10.0.20.10
- [ ] Kubernetes API accessible

---

## 4.4 Rolling Migration of Kubernetes Workers

### Step-by-Step Instructions:

> [!IMPORTANT]
> Migrate ONE node at a time. Wait for "Ready" status before proceeding to the next node.

**Migration Order** (standard workers first, GPU nodes last):

| Order | Node       | From Linksys | To TPLink Port | New IP     |
|-------|------------|--------------|----------------|------------|
| 1     | charmander | Current port | Port 3         | 10.0.20.11 |
| 2     | squirtle   | Current port | Port 4         | 10.0.20.12 |
| 3     | bulbasaur  | Current port | Port 5         | 10.0.20.13 |
| 4     | pikachu    | Current port | Port 6         | 10.0.20.14 |
| 5     | chikorita  | Current port | Port 7         | 10.0.20.15 |
| 6     | cyndaquil  | Current port | Port 8         | 10.0.20.16 |
| 7     | totodile   | Current port | Port 9         | 10.0.20.17 |
| 8     | growlithe  | Current port | Port 10        | 10.0.20.18 |
| 9     | arcanine   | Current port | Port 11        | 10.0.20.19 |
| 10    | sprigatito | Current port | (use extra)    | 10.0.20.20 |

**For EACH worker, follow this process:**

1. **Check current cluster state**
   ```bash
   kubectl get nodes -o wide | grep -E "NAME|Ready"
   
   # All other migrated nodes should show "Ready"
   ```

2. **Migrate the node**
   - [ ] **[HUMAN ACTION]** Unplug [node_name] from Linksys
   - [ ] **[HUMAN ACTION]** Plug into TPLink Port [X]
   - Note time: _________

3. **Wait and verify**
   ```bash
   # Monitor node status (repeat for up to 2 minutes)
   kubectl get nodes -o wide
   
   # Node should transition:
   # NotReady → Ready
   # IP should change to 10.0.20.XX
   ```

4. **Verify workloads**
   ```bash
   # Check for any pods stuck on this node
   kubectl get pods -A -o wide | grep [node_name]
   
   # All pods should be Running
   ```

5. **Record success and proceed**
   - [ ] Node [name] migrated and Ready
   - Proceed to next node only after "Ready" status confirmed

**Worker Migration Checklist:**
- [ ] charmander → Port 3 → 10.0.20.11 → Ready
- [ ] squirtle → Port 4 → 10.0.20.12 → Ready
- [ ] bulbasaur → Port 5 → 10.0.20.13 → Ready
- [ ] pikachu → Port 6 → 10.0.20.14 → Ready
- [ ] chikorita → Port 7 → 10.0.20.15 → Ready
- [ ] cyndaquil → Port 8 → 10.0.20.16 → Ready
- [ ] totodile → Port 9 → 10.0.20.17 → Ready
- [ ] growlithe → Port 10 → 10.0.20.18 → Ready
- [ ] arcanine (GPU) → Port 11 → 10.0.20.19 → Ready
- [ ] sprigatito (GPU) → (extra port) → 10.0.20.20 → Ready

---

## 4.5 Migrate Raspberry Pi Side Projects

### Step-by-Step Instructions:

> [!NOTE]
> These are lower priority. They can be migrated in any order or in parallel.

| Pi        | To TPLink Port | Expected IP  |
|-----------|----------------|--------------|
| mario     | Port 12        | 10.0.30.10   |
| flareon   | Port 13        | 10.0.30.11   |
| jolteon   | Port 14        | 10.0.30.12   |
| vaporeon  | Port 15        | 10.0.30.13   |
| glaceon   | Port 16        | 10.0.30.14   |
| (spare)   | Port 17        | 10.0.30.15   |
| (spare)   | Port 18        | 10.0.30.16   |

**For each Raspberry Pi:**

1. **Migrate**
   - [ ] **[HUMAN ACTION]** Unplug [pi_name] from Linksys
   - [ ] **[HUMAN ACTION]** Plug into TPLink Port [X]

2. **Verify (if Pi is running SSH)**
   ```bash
   # Wait 30-60 seconds, then try SSH
   ssh pi@[new_ip]
   
   # Or ping
   ping [new_ip]
   ```

**Raspberry Pi Checklist:**
- [ ] mario → Port 12 → 10.0.30.10
- [ ] flareon → Port 13 → 10.0.30.11
- [ ] jolteon → Port 14 → 10.0.30.12
- [ ] vaporeon → Port 15 → 10.0.30.13
- [ ] glaceon → Port 16 → 10.0.30.14

---

## 4.6 Migrate Wireless Access Point

### Step-by-Step Instructions:

1. **Pre-migration**
   - [ ] **[HUMAN ACTION]** Note all currently connected wireless devices
   - [ ] **[HUMAN ACTION]** Inform users of potential brief wireless outage

2. **Migrate AP**
   - [ ] **[HUMAN ACTION]** Unplug TPLink AX5400 AP from Linksys
   - [ ] **[HUMAN ACTION]** Plug into TPLink Switch **Port 22** (Trunk port)

3. **Verify AP connectivity**
   - Wait 30-60 seconds for AP to boot/reconnect
   - [ ] **[HUMAN ACTION]** Check AP management interface:
     - Should be accessible at 10.0.10.3 (Management VLAN)
   - [ ] **[HUMAN ACTION]** Verify SSIDs are broadcasting

4. **Configure VLAN-tagged wireless (if supported)**
   - Access AP management interface
   - If AP supports multi-SSID with VLAN tagging:
     ```
     Main SSID:
     - VLAN: 50 (IoT/Wireless)
     ```
   - [ ] **[HUMAN ACTION]** Configure VLAN tagging on AP SSIDs if supported

5. **Test wireless**
   - [ ] **[HUMAN ACTION]** Connect a device to main SSID
     - Verify IP in 10.0.50.x range
     - Verify internet access

- [ ] Wireless AP migrated and functional

---

## 4.7 Decision: Linksys Unmanaged Switch

### Step-by-Step Decision Process:

1. **Count remaining devices needing ports**
   - Current TPLink port usage after migration: ~18-20 ports
   - Available ports: 4-6

2. **Evaluate need for additional ports**
   
   **Option A: Remove Linksys Entirely** (Recommended)
   - Pros: Simpler architecture, no unmanaged segment
   - Cons: Limited expansion room
   - [ ] **[HUMAN DECISION]** Choose this if 24 ports are sufficient

   **Option B: Keep Linksys for Expansion**
   - If keeping:
     - [ ] **[HUMAN ACTION]** Connect Linksys uplink to TPLink Port 14 (Reserved)
     - [ ] **[HUMAN ACTION]** Configure Port 14 as access port for single VLAN (e.g., VLAN 50)
     - All Linksys-connected devices will be on that single VLAN
   - [ ] **[HUMAN DECISION]** Choose this if more than 24 ports needed

3. **If removing Linksys:**
   - [ ] **[HUMAN ACTION]** Verify no devices remain connected to Linksys
   - [ ] **[HUMAN ACTION]** Power off Linksys switch
   - [ ] **[HUMAN ACTION]** Physically remove Linksys from rack
   - [ ] **[HUMAN ACTION]** Store or repurpose Linksys switch

> [!IMPORTANT]
> **Checkpoint**: Before proceeding to Phase 5, verify:
> - All devices migrated to TPLink switch
> - All K8s nodes showing "Ready"
> - Twingate still working from remote
> - All VLANs functional with correct IP assignments

---
