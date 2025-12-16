# PHASE 3: Firewall Rules Configuration (SIMPLIFIED)

**Estimated Duration**: 15 minutes  
**Downtime Risk**: Low  
**Human Required**: ❌ Automated via config file

---

> [!IMPORTANT]
> **This phase has been simplified.** Instead of complex per-VLAN rules, we now use "God Mode" (allow any-to-any) rules on all interfaces to enable full inter-VLAN communication.

## 3.1 Aliases (Already Created)

The following aliases are pre-configured in `opnsense-config.xml`:

| Alias Name     | Type    | Content           | Description                    |
|----------------|---------|-------------------|--------------------------------|
| RFC1918        | Network | 10.0.0.0/8, etc.  | All private address space      |
| K8S_CLUSTER    | Network | 10.0.20.0/24      | Kubernetes Production Network  |
| CLUSTER_EXTRA  | Network | 10.0.30.0/24      | Cluster Extra VLAN 30          |
| STORAGE_NET    | Network | 10.0.40.0/24      | Storage VLAN Network           |
| IOT_NET        | Network | 10.0.50.0/24      | IoT Network VLAN 50            |
| TWINGATE_NAS   | Host    | 10.0.40.3         | UNRAID NAS                     |
| MGMT_DEVICES   | Network | 10.0.10.0/24      | Management VLAN devices        |
| NFS_PORTS      | Port    | 111, 2049, 20048  | NFS service ports              |
| SMB_PORTS      | Port    | 139, 445          | SMB/CIFS service ports         |

---

## 3.2 Firewall Rules (Simplified - God Mode)

All interfaces are configured with a single "Allow All" rule:

| Interface    | VLAN | Rule Description                    |
|--------------|------|-------------------------------------|
| lan          | -    | LAN Allow All (God Mode)            |
| opt1         | 10   | Management Allow All (God Mode)     |
| opt2         | 20   | ClusterProd Allow All (God Mode)    |
| opt3         | 30   | ClusterExtra Allow All (God Mode)   |
| opt4         | 40   | Storage Allow All (God Mode)        |
| opt5         | 50   | IoT/Wireless Allow All (God Mode)   |

### What This Means

- **All devices can communicate with all other devices** across VLANs
- **No inter-VLAN restrictions** - full network visibility
- **Simpler to troubleshoot** - if connectivity fails, it's not a firewall issue
- **Internet access** works from all VLANs (NAT via WAN)

---

## 3.3 Applying the Configuration

### Option A: Restore Config File (Recommended)

1. **Backup current config**
   ```bash
   scp root@10.0.10.1:/conf/config.xml ./config-backup-$(date +%Y%m%d).xml
   ```

2. **Upload new config**
   - [ ] **[HUMAN ACTION]** Go to `System` → `Configuration` → `Backups`
   - [ ] **[HUMAN ACTION]** Upload `opnsense-config.xml` from this repository
   - [ ] **[HUMAN ACTION]** Click `Restore`
   - [ ] **[HUMAN ACTION]** Reboot OPNSense

### Option B: Manual UI Configuration

For each interface (opt1, opt2, opt3, opt4):

1. Go to `Firewall` → `Rules` → `[Interface Name]`
2. Delete any existing restrictive rules
3. Add new rule:
   ```
   Action: Pass
   Interface: [current interface]
   Protocol: any
   Source: any
   Destination: any
   Description: [Interface] Allow All (God Mode)
   ```
4. Click Save
5. Apply Changes

---

## 3.4 Verification

After applying changes:

```bash
# From a device on VLAN 50 (AP/Wireless):
ping 10.0.10.1   # OPNSense Management interface
ping 10.0.10.2   # TPLink Switch
ping 10.0.20.10  # Kubernetes control plane (ash)
ping 10.0.40.3   # NAS

# Test Kubernetes
kubectl get nodes
```

> [!TIP]
> If connectivity still fails after applying rules, check:
> - Switch VLAN configuration (trunk ports, PVID)
> - DHCP lease renewed on client
> - Physical cable connections

---

## Previous Segmented Approach (Deprecated)

The original Phase 3 used segmented firewall rules with specific allow/deny policies per VLAN. This approach is no longer used. For reference, the old rules are documented in the git history of this file.
