# PHASE 2: OPNSense VLAN Configuration
**Estimated Duration**: 60-90 minutes  
**Downtime Risk**: Low (during interface assignment)  
**Human Required**: ✅ Web UI configuration

---

## 2.0 Create LAGG Interface (Link Aggregation)

> [!IMPORTANT]
> **Create the LAGG first** before creating VLANs. VLANs will be created on the LAGG interface, not directly on eth1/eth2.

### Step-by-Step Instructions:

1. **Login to OPNSense web interface**
   - [ ] **[HUMAN ACTION]** Open browser: `https://10.0.0.1`
   - [ ] **[HUMAN ACTION]** Login with admin credentials

2. **Navigate to LAGG configuration**
   - [ ] **[HUMAN ACTION]** Go to `Interfaces` → `Other Types` → `LAGG`
   - [ ] **[HUMAN ACTION]** Click `+` to add a new LAGG

3. **Create LAGG0**
   ```
   Parent Interfaces: Select eth1 AND eth2 (Ctrl+Click to multi-select)
   Protocol: Loadbalance (NOT LACP - switch doesn't support LACP)
   Description: LAN_LAG
   ```
   - [ ] **[HUMAN ACTION]** Click Save
   - [ ] **[HUMAN ACTION]** Click Apply Changes

4. **Verify LAGG is created**
   - [ ] **[HUMAN ACTION]** You should see `lagg0` in the list
   - Status should show both member ports

---

## 2.1 Create VLAN Interfaces on LAGG0

### Step-by-Step Instructions:

1. **Navigate to VLAN device configuration**
   - [ ] **[HUMAN ACTION]** Go to `Interfaces` → `Other Types` → `VLAN`
   - [ ] **[HUMAN ACTION]** Click the `+` button to add a new VLAN

2. **Create VLAN 10 (Management)**
   ```
   Parent: lagg0 (the LAG you just created)
   VLAN Tag: 10
   Description: Management
   ```
   - [ ] **[HUMAN ACTION]** Click Save
   - [ ] VLAN 10 created

3. **Create VLAN 20 (Cluster-Prod)**
   - [ ] **[HUMAN ACTION]** Click `+` again
   ```
   Parent: lagg0
   VLAN Tag: 20
   Description: Cluster-Prod
   ```
   - [ ] **[HUMAN ACTION]** Click Save
   - [ ] VLAN 20 created

4. **Create VLAN 30 (Cluster-Extra)**
   - [ ] **[HUMAN ACTION]** Click `+` again
   ```
   Parent: lagg0
   VLAN Tag: 30
   Description: Cluster-Extra
   ```
   - [ ] **[HUMAN ACTION]** Click Save
   - [ ] VLAN 30 created

5. **Create VLAN 40 (Storage)**
   - [ ] **[HUMAN ACTION]** Click `+` again
   ```
   Parent: lagg0
   VLAN Tag: 40
   Description: Storage
   ```
   - [ ] **[HUMAN ACTION]** Click Save
   - [ ] VLAN 40 created

6. **Create VLAN 50 (IoT-Wireless)**
   - [ ] **[HUMAN ACTION]** Click `+` again
   ```
   Parent: lagg0
   VLAN Tag: 50
   Description: IoT-Wireless
   ```
   - [ ] **[HUMAN ACTION]** Click Save
   - [ ] VLAN 50 created

7. **Apply changes**
   - [ ] **[HUMAN ACTION]** Click `Apply` at top of page if prompted

---

## 2.2 Assign and Configure VLAN Interfaces

### Step-by-Step Instructions:

1. **Navigate to interface assignments**
   - [ ] **[HUMAN ACTION]** Go to `Interfaces` → `Assignments`
   - You'll see a dropdown at the bottom saying "Available network ports"

2. **Assign VLAN 10 (Management)**
   - [ ] **[HUMAN ACTION]** Select `vlan 0.10 on eth1 - Management` from dropdown
   - [ ] **[HUMAN ACTION]** Click `+` to add
   - [ ] **[HUMAN ACTION]** Click on the new interface (e.g., OPT1)
   - Configure:
   ```
   Enable: ✅ Checked
   Description: Management
   IPv4 Configuration Type: Static IPv4
   IPv4 Address: 10.0.10.1 / 24
   ```
   - [ ] **[HUMAN ACTION]** Click Save
   - [ ] **[HUMAN ACTION]** Click Apply Changes

3. **Assign VLAN 20 (Cluster-Prod)**
   - [ ] **[HUMAN ACTION]** Go back to `Interfaces` → `Assignments`
   - [ ] **[HUMAN ACTION]** Select `vlan 0.20 on eth1 - Cluster-Prod` from dropdown
   - [ ] **[HUMAN ACTION]** Click `+` to add
   - [ ] **[HUMAN ACTION]** Click on the new interface
   - Configure:
   ```
   Enable: ✅ Checked
   Description: Cluster-Prod
   IPv4 Configuration Type: Static IPv4
   IPv4 Address: 10.0.20.1 / 24
   ```
   - [ ] **[HUMAN ACTION]** Click Save
   - [ ] **[HUMAN ACTION]** Click Apply Changes

4. **Assign VLAN 30 (Cluster-Extra)**
   - [ ] **[HUMAN ACTION]** Repeat assignment process
   - Configure:
   ```
   Enable: ✅ Checked
   Description: Cluster-Extra
   IPv4 Configuration Type: Static IPv4
   IPv4 Address: 10.0.30.1 / 24
   ```
   - [ ] **[HUMAN ACTION]** Save and Apply

5. **Assign VLAN 40 (Storage)**
   - [ ] **[HUMAN ACTION]** Repeat assignment process
   - Configure:
   ```
   Enable: ✅ Checked
   Description: STORAGE
   IPv4 Configuration Type: Static IPv4
   IPv4 Address: 10.0.40.1 / 24
   ```
   - [ ] **[HUMAN ACTION]** Save and Apply

6. **Assign VLAN 50 (IoT-Wireless)**
   - [ ] **[HUMAN ACTION]** Repeat assignment process
   - Configure:
   ```
   Enable: ✅ Checked
   Description: IoT-Wireless
   IPv4 Configuration Type: Static IPv4
   IPv4 Address: 10.0.50.1 / 24
   ```
   - [ ] **[HUMAN ACTION]** Save and Apply

7. **Verify all interfaces**
   - [ ] **[HUMAN ACTION]** Go to `Interfaces` → `Overview`
   - Confirm all 5 VLAN interfaces show "up" with correct IPs

---

## 2.3 Configure DHCP for Each VLAN (Kea DHCPv4)

### Step-by-Step Instructions:

1. **Navigate to DHCP configuration**
   - [ ] **[HUMAN ACTION]** Go to `Services` → `Kea DHCP` → `DHCPv4`
   - You'll see a Subnets section listing all configured interfaces

2. **Configure DHCP for VLAN 10 (Management)**
   - [ ] **[HUMAN ACTION]** Click `+` to add a new subnet (or edit existing)
   - Configure:
   ```
   Subnet: 10.0.10.0/24
   Pools: 10.0.10.100-10.0.10.254
   Option Data:
     - DNS Servers: 10.0.10.1
     - Routers: 10.0.10.1
   ```
   - [ ] **[HUMAN ACTION]** Click Save


3. **Configure DHCP for VLAN 20 (Cluster-Prod)**
   - [ ] **[HUMAN ACTION]** Click `+` to add subnet
   - Configure:
   ```
   Subnet: 10.0.20.0/24
   Pools: 10.0.20.100-10.0.20.254
   Option Data:
     - DNS Servers: 10.0.20.1
     - Routers: 10.0.20.1
   ```
   - [ ] **[HUMAN ACTION]** Click Save

4. **Configure DHCP for VLAN 30 (Cluster-Extra)**
   - [ ] **[HUMAN ACTION]** Click `+` to add subnet
   - Configure:
   ```
   Subnet: 10.0.30.0/24
   Pools: 10.0.30.100-10.0.30.254
   Option Data:
     - DNS Servers: 10.0.30.1
     - Routers: 10.0.30.1
   ```
   - [ ] **[HUMAN ACTION]** Click Save

5. **Configure DHCP for VLAN 40 (Storage)**
   - [ ] **[HUMAN ACTION]** Click `+` to add subnet
   - Configure:
   ```
   Subnet: 10.0.40.0/24
   Pools: 10.0.40.100-10.0.40.254
   Option Data:
     - DNS Servers: 10.0.40.1
     - Routers: 10.0.40.1
   ```
   - [ ] **[HUMAN ACTION]** Click Save

6. **Configure DHCP for VLAN 50 (IoT-Wireless)**
   - [ ] **[HUMAN ACTION]** Click `+` to add subnet
   - Configure:
   ```
   Subnet: 10.0.50.0/24
   Pools: 10.0.50.100-10.0.50.254
   Option Data:
     - DNS Servers: 10.0.50.1
     - Routers: 10.0.50.1
   ```
   - [ ] **[HUMAN ACTION]** Click Save

7. **Apply all changes**
   - [ ] **[HUMAN ACTION]** Click `Apply` if prompted

---

## 2.4 Create DHCP Static Reservations (Kea)

### Step-by-Step Instructions:

1. **Navigate to Kea Reservations**
   - [ ] **[HUMAN ACTION]** Go to `Services` → `Kea DHCP` → `Reservations`
   - [ ] **[HUMAN ACTION]** Click `+` to add new reservation


2. **Add reservation for ash (K8s Controller)**
   - Select Subnet: `10.0.20.0/24` (Cluster-Prod)
   ```
   HW Address: dc:a6:32:d2:c5:48
   IP Address: 10.0.20.10
   Hostname: ash
   Description: K8s Controller Node
   ```
   - [ ] **[HUMAN ACTION]** Click Save


3. **Add reservations for all K8s workers**
   
   Repeat the add process for each node (all in subnet 10.0.20.0/24):

   | HW Address         | IP Address   | Hostname   |
   |--------------------|--------------|------------|
   | 00:23:24:b0:ff:03  | 10.0.20.11   | charmander |
   | 00:23:24:e2:1f:a1  | 10.0.20.12   | squirtle   |
   | 00:23:24:e2:0d:ea  | 10.0.20.13   | bulbasaur  |
   | e0:4f:43:24:0b:53  | 10.0.20.14   | pikachu    |
   | 6c:4b:90:60:29:c4  | 10.0.20.15   | chikorita  |
   | 6c:4b:90:5f:8e:43  | 10.0.20.16   | cyndaquil  |
   | 6c:4b:90:5b:a3:56  | 10.0.20.17   | totodile   |
   | 6c:4b:90:5b:6e:6d  | 10.0.20.18   | growlithe  |
   | 4c:cc:6a:3d:e5:3f  | 10.0.20.19   | arcanine   |
   | 4c:cc:6a:34:dc:6d  | 10.0.20.20   | sprigatito |

   - [ ] All 11 K8s node reservations created


4. **Add reservation for UNRAID NAS (CRITICAL for Twingate)**
   - Select Subnet: `10.0.40.0/24` (Storage)
   - [ ] **[HUMAN ACTION]** Click `+` to add
   ```
   HW Address: 00:e0:4c:17:87:83
   IP Address: 10.0.40.3
   Hostname: unraid
   Description: UNRAID NAS - TWINGATE CRITICAL
   ```
   - [ ] **[HUMAN ACTION]** Click Save


> [!IMPORTANT]
> **Checkpoint**: Before proceeding to Phase 3, verify:
> - All 5 VLAN interfaces are enabled and have correct IP addresses
> - DHCP is enabled on all 5 VLANs with correct ranges
> - All K8s nodes have static DHCP mappings in VLAN 20
> - UNRAID has static DHCP mapping in VLAN 40
> - Take a backup of OPNSense config at this point

---
