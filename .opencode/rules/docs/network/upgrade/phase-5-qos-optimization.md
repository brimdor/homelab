# PHASE 5: QoS and Traffic Optimization
**Estimated Duration**: 30-45 minutes  
**Downtime Risk**: None  
**Human Required**: ⚠️ Policy review

---

## 5.1 Configure Traffic Shaping in OPNSense

### Step-by-Step Instructions:

1. **Navigate to Traffic Shaper**
   - [ ] **[HUMAN ACTION]** Go to `Firewall` → `Shaper` → `Settings`
   - [ ] **[HUMAN ACTION]** Enable traffic shaping: Toggle "Enable" to ON
   - [ ] **[HUMAN ACTION]** Click Save

2. **Create Pipes (bandwidth limits)**
   - [ ] **[HUMAN ACTION]** Go to `Firewall` → `Shaper` → `Pipes`
   - [ ] **[HUMAN ACTION]** Click `+` to add new pipe

   **Pipe 1: Critical Traffic (Twingate/NAS)**
   ```
   Enabled: ✅
   Bandwidth: 30
   Bandwidth Metric: %
   Queue: 50 (slots)
   Description: Critical - Twingate and NAS
   ```
   - [ ] **[HUMAN ACTION]** Click Save

   **Pipe 2: Kubernetes Production**
   ```
   Enabled: ✅
   Bandwidth: 40
   Bandwidth Metric: %
   Description: K8s Production Cluster
   ```
   - [ ] **[HUMAN ACTION]** Click Save

   **Pipe 3: Management/Interactive**
   ```
   Enabled: ✅
   Bandwidth: 15
   Bandwidth Metric: %
   Description: Management and Interactive
   ```
   - [ ] **[HUMAN ACTION]** Click Save

   **Pipe 4: Default (RPi/IoT)**
   ```
   Enabled: ✅
   Bandwidth: 15
   Bandwidth Metric: %
   Description: Default - RPi and IoT
   ```
   - [ ] **[HUMAN ACTION]** Click Save

3. **Create Queues for each pipe**
   - [ ] **[HUMAN ACTION]** Go to `Firewall` → `Shaper` → `Queues`
   - For each pipe, create a corresponding queue with appropriate weight

4. **Create Rules to classify traffic**
   - [ ] **[HUMAN ACTION]** Go to `Firewall` → `Shaper` → `Rules`
   
   **Rule: VLAN 40 (Storage) to Critical Pipe**
   ```
   Interface: Storage
   Direction: in/out
   Target: Pipe 1 (Critical)
   Description: Storage VLAN to Critical pipe
   ```
   - [ ] **[HUMAN ACTION]** Click Save

   **Rule: VLAN 20 (K8s) to K8s Pipe**
   ```
   Interface: Cluster-Prod
   Target: Pipe 2 (K8s Production)
   Description: K8s traffic shaping
   ```
   - [ ] **[HUMAN ACTION]** Click Save

   Continue for remaining VLANs...

5. **Apply shaper configuration**
   - [ ] **[HUMAN ACTION]** Click Apply at top of page

---

## 5.2 Enable Jumbo Frames (Optional - High Performance)

### Step-by-Step Instructions:

> [!WARNING]
> Jumbo frames require ALL devices in the path to support the same MTU. This includes: Switch → Router → Server. Mismatched MTU causes silent packet drops and performance issues. Only proceed if you understand the implications.

1. **Enable on TPLink Switch first**
   - [ ] **[HUMAN ACTION]** Access TPLink switch at `http://10.0.0.2`
   - [ ] **[HUMAN ACTION]** Navigate to: `Switching` → `Jumbo Frame` (or similar)
   - [ ] **[HUMAN ACTION]** Enable Jumbo Frames with MTU: 9000
   - [ ] **[HUMAN ACTION]** Apply to ports in VLAN 20 and VLAN 40
   - [ ] **[HUMAN ACTION]** Save configuration

2. **Configure OPNSense VLAN interfaces**
   - [ ] **[HUMAN ACTION]** Go to `Interfaces` → `[Cluster-Prod]`
   - [ ] **[HUMAN ACTION]** Set MTU to: 9000
   - [ ] **[HUMAN ACTION]** Click Save
   
   - [ ] **[HUMAN ACTION]** Go to `Interfaces` → `[Storage]`
   - [ ] **[HUMAN ACTION]** Set MTU to: 9000
   - [ ] **[HUMAN ACTION]** Click Save
   
   - [ ] **[HUMAN ACTION]** Apply changes

3. **Configure UNRAID NAS**
   - [ ] **[HUMAN ACTION]** Access UNRAID web UI
   - [ ] **[HUMAN ACTION]** Go to `Settings` → `Network Settings`
   - [ ] **[HUMAN ACTION]** Set MTU to: 9000
   - [ ] **[HUMAN ACTION]** Apply

4. **Configure Kubernetes Nodes**
   - For each node, SSH and configure MTU:
   ```bash
   # SSH to node
   ssh user@10.0.20.XX
   
   # Edit network configuration (method depends on OS)
   # For Ubuntu/Debian with netplan:
   sudo nano /etc/netplan/00-installer-config.yaml
   
   # Add mtu: 9000 under the ethernet interface
   # Example:
   # network:
   #   ethernets:
   #     eth0:
   #       mtu: 9000
   #       dhcp4: true
   
   # Apply changes
   sudo netplan apply
   ```

5. **Verify MTU end-to-end**
   ```bash
   # From K8s node to NAS, test with large packet
   ping -M do -s 8972 10.0.40.3
   
   # If successful (no fragmentation), jumbo frames are working
   # If fails with "message too long", MTU mismatch exists
   ```

- [ ] Jumbo frames verified working (optional)

> [!IMPORTANT]
> **Checkpoint**: QoS and optional optimizations complete. Proceed to verification.

---
