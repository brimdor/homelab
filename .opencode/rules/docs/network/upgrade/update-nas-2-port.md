# Steps to Update Switch & OPNSense for NAS 2-Port Configuration

> [!IMPORTANT]
> These steps update the existing configuration to allocate **two ports** (19-20) for the UNRAID NAS instead of one.

---

## Summary of Port Changes

| Port(s) | OLD Config | NEW Config |
|---------|-----------|------------|
| 19 | VLAN 40 - NAS | VLAN 40 - NAS Port 1 |
| **20** | **VLAN 50 - IoT** | **VLAN 40 - NAS Port 2** |
| **21** | **VLAN 50 - IoT** | **VLAN 50 - IoT (only port)** |

---

## Part 1: TPLink Switch Configuration Update

### Step 1.1: Access the Switch
1. Open browser and navigate to: `http://10.0.0.2`
2. Login with admin credentials

### Step 1.2: Change Port 20 from VLAN 50 to VLAN 40
1. Navigate to: `L2 Features` → `VLAN` → `802.1Q VLAN` → `Port Config`
   - *(Alternative: `VLAN` → `Port Based VLAN`)*

2. **Remove Port 20 from VLAN 50:**
   - Select VLAN 50
   - Find Port 20
   - Set Port 20 to: **Not Member** (remove from VLAN 50)
   - Click Apply

3. **Add Port 20 to VLAN 40:**
   - Select VLAN 40
   - Find Port 20
   - Set Port 20 to: **Untagged** (U)
   - Click Apply

4. **Update Port 20 PVID:**
   - Navigate to: `VLAN` → `802.1Q VLAN` → `PVID Setting`
   - Find Port 20
   - Change PVID from **50** to **40**
   - Click Apply

### Step 1.3: Verify Port 21 is still on VLAN 50
1. Navigate to: `Port Config` or `PVID Setting`
2. Verify Port 21 shows PVID = **50**
3. Verify Port 21 is **Untagged** member of VLAN 50

### Step 1.4: Save Configuration
1. Navigate to: `System` → `System Tools` → `Config Restore/Backup`
2. Click **Save** to save running config to startup
3. *(Optional)* Click **Backup** to export configuration file

### Verification (Switch)
After saving, verify the port configuration matches:

| Port | VLAN | Mode | PVID | Device |
|------|------|------|------|--------|
| 19 | 40 | Access | 40 | NAS Port 1 |
| 20 | 40 | Access | 40 | NAS Port 2 |
| 21 | 50 | Access | 50 | IoT |

---

## Part 2: OPNSense Configuration Update

> [!NOTE]
> OPNSense doesn't require any VLAN or interface changes for this update.
> Only DHCP static mappings need to be verified if your NAS uses bonding.

### Step 2.1: Verify DHCP Static Mapping (Storage VLAN 40)
1. Login to OPNSense: `https://10.0.0.1`
2. Navigate to: `Services` → `ISC DHCPv4` → `[Storage]` interface (VLAN 40)
3. Scroll to **Static Mappings**
4. Verify UNRAID NAS static mapping exists:
   - **MAC Address**: (your NAS primary MAC)
   - **IP Address**: `10.0.40.3`
   - **Hostname**: `unraid` or similar

If your NAS uses NIC bonding, the bond MAC will be what appears to DHCP. No additional mapping is needed for the second physical port if bonding is configured on the NAS side.

### Step 2.2: If NOT Using Bonding (Two Separate IPs)
If your NAS exposes two separate network interfaces (not bonded), you may want to:

1. Add a second static DHCP mapping:
   - Navigate to: `Services` → `ISC DHCPv4` → `[Storage]`
   - Click **+** to add new static mapping
   - **MAC Address**: (NAS second NIC MAC)
   - **IP Address**: `10.0.40.4` (or another unused IP)
   - **Hostname**: `unraid-eth1`
   - Save and Apply

### Step 2.3: Verify Firewall Rules (if needed)
If you have any firewall rules that specifically reference port 20 as IoT, you may need to update them. However, since this is VLAN-based, the Storage VLAN (40) rules should already permit traffic from any port on that VLAN.

No changes required if using standard inter-VLAN rules.

---

## Part 3: Physical Migration (If NAS Is Already Connected)

If your NAS is currently connected to a single port and you're adding the second port:

1. **[HUMAN ACTION]** Identify NAS second ethernet port
2. **[HUMAN ACTION]** Run an ethernet cable from NAS Port 2 to TPLink **Port 20**
3. **[HUMAN ACTION]** On NAS, configure bonding mode:
   - **Recommended:** `BONDING_MODE[0]="2"` (balance-xor) for best stability.
   - *Alternative:* Mode 0 (balance-rr) is possible but may cause packet reordering.
   - **CRITICAL:** Do NOT use Mode 6 (balance-alb) or Mode 4 (802.3ad) with Static LAG!
4. Verify connectivity:


   ```bash
   # From any device on the network
   ping 10.0.40.3
   
   # Check NAS web UI is accessible
   curl -sI http://10.0.40.3 | head -1
   ```

---

## Quick Reference: Final Port Layout

```
TPLink 24-Port Switch
├── Port 1:      VLAN 10 (Management)      - Temp/Laptop
├── Ports 2-11:  VLAN 20 (Cluster-Prod)    - K8s (10 nodes)
├── Ports 12-18: VLAN 30 (Cluster-Extra)   - Raspberry Pis (7)
├── Port 19:     VLAN 40 (Storage)         - NAS Port 1 ★
├── Port 20:     VLAN 40 (Storage)         - NAS Port 2 ★ (NEW)
├── Port 21:     VLAN 50 (IoT)             - IoT devices
├── Port 22:     Trunk (VLAN 10+50)        - Access Point
└── Ports 23-24: LAG1 (Static)             - OPNSense uplink
```

---

## Checklist

- [ ] TPLink: Port 20 removed from VLAN 50
- [ ] TPLink: Port 20 added to VLAN 40 (Untagged)
- [ ] TPLink: Port 20 PVID changed to 40
- [ ] TPLink: Configuration saved
- [ ] OPNSense: DHCP static mapping verified for NAS
- [ ] Physical: NAS second port connected to TPLink Port 20
- [ ] Tested: NAS connectivity verified
