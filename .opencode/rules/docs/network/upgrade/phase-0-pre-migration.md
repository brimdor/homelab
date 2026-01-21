# PHASE 0: Pre-Migration Preparation
**Estimated Duration**: 30-60 minutes  
**Downtime Risk**: None  
**Human Required**: ✅ Backup verification

---

## 0.1 Backup OPNSense Configuration

### Step-by-Step Instructions:

1. **Open browser and navigate to OPNSense web interface**
   - URL: `https://10.0.0.1` or your current OPNSense IP
   - Login with admin credentials

2. **Navigate to backup section**
   - Click `System` in the left menu
   - Click `Configuration` → `Backups`

3. **Create configuration backup**
   - In the "Download" section, leave "Encrypt this configuration file" unchecked (unless you want encrypted backup)
   - Click `Download configuration`
   - Save file as: `opnsense-backup-YYYY-MM-DD-pre-vlan.xml`

4. **Verify backup file**
   - Open the downloaded XML file in a text editor
   - Confirm it contains valid XML with `<opnsense>` root element
   - Store in: `/home/brimdor/Documents/Github/nelson_network/docs/network/backups/`

- [ ] **[HUMAN ACTION]** Download OPNSense configuration backup from web UI
- [ ] **[HUMAN ACTION]** Verify backup file is valid XML and contains configuration data

---

## 0.2 Document Current Switch Port Mappings

### Step-by-Step Instructions:

1. **Physical inspection of Linksys switch**
   - Go to server rack location
   - For EACH occupied port on the Linksys switch:
     - Trace the cable to its connected device
     - Note the port number and device name

2. **Create port mapping document**
   - Create or update file: `docs/network/current-port-mapping.md`
   - Document each connection in table format:
   ```
   | Port | Device | Current IP | Cable Color/Label |
   |------|--------|------------|-------------------|
   | 1    | UNRAID | 10.0.40.3  | Blue              |
   | 2    | ash    | 10.0.20.10| Yellow            |
   ...etc
   ```

3. **Take photos**
   - Photograph front of switch showing port numbering
   - Photograph cable connections for reference
   - Save photos to: `docs/network/images/pre-migration/`

- [ ] **[HUMAN ACTION]** Physically trace and document all current switch connections
- [ ] **[HUMAN ACTION]** Take photos of current switch cabling

---

## 0.3 Verify Twingate Connectivity

### Step-by-Step Instructions:

1. **Check Twingate connector status on UNRAID**
   ```bash
   # SSH into UNRAID or access console
   ssh root@10.0.40.3
   
   # Check Docker containers
   docker ps | grep twingate
   
   # Verify connector is running (should show "Up" status)
   ```

2. **Test Twingate from remote location**
   - From a device OUTSIDE the local network (phone on cellular, or remote machine)
   - Open Twingate client
   - Navigate to `Geek Network` resources
   - Verify you can connect to at least one internal resource

3. **Document Twingate connector details**
   ```bash
   # Get connector container IDs
   docker ps --filter name=twingate --format "table {{.ID}}\t{{.Names}}\t{{.Status}}"
   
   # Note the container names for potential recovery
   ```

4. **Access Twingate Admin Console**
   - Login to: `https://admin.twingate.com`
   - Navigate to `Network` → `Connectors`
   - Verify connector status shows "Online" (green)
   - Screenshot the connector status page

- [ ] **[HUMAN ACTION]** SSH to UNRAID and verify Twingate Docker containers are running
- [ ] **[HUMAN ACTION]** Test Twingate access from a remote location
- [ ] **[HUMAN ACTION]** Verify connector status in Twingate admin console

---

## 0.4 Verify Hardware Readiness

### Step-by-Step Instructions:

1. **Locate TPLink managed switch**
   - Find the TPLink 24-Port Managed Switch
   - Verify MAC address on bottom label: `14:EB:B6:0D:F2:B2`
   - Ensure power cable is available

2. **Prepare ethernet cables**
   - Count current devices to migrate: approximately 15-20 cables needed
   - Prepare at least 5 extra cables for contingency
   - Label cables if possible (use tape + marker)

3. **Identify OPNSense interfaces**
   ```bash
   # SSH to OPNSense or access console
   ssh root@10.0.0.1
   
   # List network interfaces
   ifconfig | grep -E "^[a-z]"
   
   # Or in web UI: Interfaces → Overview
   # Document which port is WAN vs LAN
   ```

4. **Prepare staging area**
   - Clear space near rack for TPLink switch placement
   - Ensure power outlet is available
   - Plan physical placement for cable routing

- [ ] **[HUMAN ACTION]** Physically locate and verify TPLink switch
- [ ] **[HUMAN ACTION]** Prepare sufficient ethernet cables
- [ ] **[HUMAN ACTION]** Verify OPNSense interface assignments (eth0=WAN, eth1/eth2=LAN)

---

## 0.5 Document Current Network State

### Step-by-Step Instructions:

1. **Ping test all critical devices**
   ```bash
   # Create and run network test script
   #!/bin/bash
   echo "=== Pre-Migration Network Test ==="
   echo "Date: $(date)"
   echo ""
   
   declare -A hosts=(
     ["OPNSense"]="10.0.0.1"
     ["UNRAID"]="10.0.40.3"
     ["ash (K8s Controller)"]="10.0.20.10"
     ["charmander"]="10.0.50.121"
     ["squirtle"]="10.0.50.122"
     ["bulbasaur"]="10.0.50.123"
     ["pikachu"]="10.0.50.124"
   )
   
   for name in "${!hosts[@]}"; do
     ip="${hosts[$name]}"
     if ping -c 1 -W 2 "$ip" &>/dev/null; then
       echo "✅ $name ($ip): REACHABLE"
     else
       echo "❌ $name ($ip): UNREACHABLE"
     fi
   done
   ```

2. **Verify Kubernetes cluster health**
   ```bash
   # Check all nodes
   kubectl get nodes -o wide
   
   # Verify all nodes show "Ready"
   kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}'
   ```

3. **Check critical services**
   ```bash
   # ArgoCD
   curl -sI https://argocd.eaglepass.io | head -1
   
   # Gitea  
   curl -sI https://git.eaglepass.io | head -1
   
   # Grafana
   curl -sI https://grafana.eaglepass.io | head -1
   ```

4. **Export current DHCP leases**
   - OPNSense: `Services` → `ISC DHCPv4` → `Leases`
   - Screenshot or export the current leases list
   - Save to: `docs/network/pre-migration-dhcp-leases.txt`

- [ ] Document all current IP assignments with ping verification
- [ ] Verify Kubernetes cluster is healthy
- [ ] Verify all critical applications are accessible
- [ ] Export current DHCP lease list from OPNSense

> [!IMPORTANT]
> **Checkpoint**: Do not proceed to Phase 1 until:
> - OPNSense backup is downloaded and verified
> - Twingate connectivity is confirmed from remote location
> - All production services are verified operational
> - Current network state is fully documented

---
