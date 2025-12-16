# PHASE 7: Documentation and Cleanup
**Estimated Duration**: 30 minutes  
**Downtime Risk**: None  
**Human Required**: ⚠️ Documentation review

---

## 7.1 Update Network Documentation

### Step-by-Step Instructions:

1. **Update network diagram**
   - [ ] **[HUMAN ACTION]** Edit `docs/network/diagram.md`
   - Add new VLAN topology diagram showing:
     - VLAN IDs and names
     - Port assignments on TPLink switch
     - OPNSense as inter-VLAN router
     - Device placements

2. **Update network overview**
   - [ ] **[HUMAN ACTION]** Edit `docs/network/overview.md`
   - Update with:
     - New IP ranges for each VLAN
     - New device IP assignments
     - DHCP ranges
     - Firewall policy summary

3. **Create VLAN reference document**
   - [ ] **[HUMAN ACTION]** Create `docs/network/vlan-reference.md`
   - Include:
   ```markdown
   # VLAN Reference Guide
   
   | VLAN | Name         | Network       | Gateway     | Purpose              |
   |------|--------------|---------------|-------------|----------------------|
   | 1    | Native       | 10.0.0.0/24   | 10.0.0.1    | Infrastructure       |
   | 10   | Management   | 10.0.10.0/24  | 10.0.10.1   | Switch/AP management |
   | 20   | Cluster-Prod | 10.0.20.0/24  | 10.0.20.1   | Kubernetes cluster   |
   | 30   | Cluster-Extra| 10.0.30.0/24  | 10.0.30.1   | Raspberry Pi projects|
   | 40   | Storage      | 10.0.40.0/24  | 10.0.40.1   | NAS/Twingate         |
   | 50   | IoT-Wireless | 10.0.50.0/24  | 10.0.50.1   | Wireless/IoT devices |
   ```

4. **Update device inventory**
   - [ ] **[HUMAN ACTION]** Update any device inventory documents with new IPs

---

## 7.2 Backup Final Configurations

### Step-by-Step Instructions:

1. **Export OPNSense configuration**
   - [ ] **[HUMAN ACTION]** Go to `System` → `Configuration` → `Backups`
   - [ ] **[HUMAN ACTION]** Click `Download configuration`
   - [ ] **[HUMAN ACTION]** Save as: `opnsense-backup-YYYY-MM-DD-post-vlan.xml`
   - [ ] **[HUMAN ACTION]** Store in: `docs/network/backups/`

2. **Export TPLink Switch configuration**
   - [ ] **[HUMAN ACTION]** Access TPLink switch at http://10.0.0.2
   - [ ] **[HUMAN ACTION]** Go to: `System` → `System Tools` → `Config Restore/Backup`
   - [ ] **[HUMAN ACTION]** Click Backup/Export
   - [ ] **[HUMAN ACTION]** Save as: `tplink-switch-config-YYYY-MM-DD-final.cfg`
   - [ ] **[HUMAN ACTION]** Store in: `docs/network/backups/`

3. **Secure backup storage**
   - [ ] **[HUMAN ACTION]** Copy backups to secure off-site location (cloud storage, etc.)
   - [ ] **[HUMAN ACTION]** Document backup locations

---

## 7.3 Physical Cleanup

### Step-by-Step Instructions:

1. **Label all cables**
   - [ ] **[HUMAN ACTION]** Create labels for each cable showing:
     - Device name
     - VLAN assignment
     - Port number
   - [ ] **[HUMAN ACTION]** Apply labels at both ends of each cable

2. **Remove old equipment (if applicable)**
   - If Linksys switch was retired:
     - [ ] **[HUMAN ACTION]** Verify no devices connected to Linksys
     - [ ] **[HUMAN ACTION]** Power off Linksys
     - [ ] **[HUMAN ACTION]** Remove from rack
     - [ ] **[HUMAN ACTION]** Coil and store unused cables
     - [ ] **[HUMAN ACTION]** Store or dispose of Linksys switch

3. **Cable management**
   - [ ] **[HUMAN ACTION]** Bundle cables neatly with velcro ties or cable management
   - [ ] **[HUMAN ACTION]** Route cables to minimize tangling
   - [ ] **[HUMAN ACTION]** Ensure adequate airflow around equipment

4. **Take photos of final setup**
   - [ ] **[HUMAN ACTION]** Photograph front of rack showing all connections
   - [ ] **[HUMAN ACTION]** Photograph cable routing
   - [ ] **[HUMAN ACTION]** Save photos to: `docs/network/images/post-migration/`

