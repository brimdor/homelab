# PHASE 6: Verification and Testing
**Estimated Duration**: 30-60 minutes  
**Downtime Risk**: None  
**Human Required**: ✅ Validation review

---

## 6.1 Connectivity Tests

### Step-by-Step Instructions:

1. **Test VLAN 10 (Management)**
   - From a device on VLAN 10:
   ```bash
   # Gateway test
   ping 10.0.10.1
   
   # Internet test
   ping 8.8.8.8
   curl -sI https://google.com | head -1
   
   # DNS test
   nslookup google.com 10.0.10.1
   ```
   - [ ] VLAN 10 connectivity verified

2. **Test VLAN 20 (K8s Production)**
   - From any K8s node:
   ```bash
   # Gateway test
   ping 10.0.20.1
   
   # Internet test
   ping 8.8.8.8
   curl -sI https://google.com | head -1
   
   # DNS test
   nslookup google.com
   ```
   - [ ] VLAN 20 connectivity verified

3. **Test VLAN 30 (K8s Extra)**
   - From any Raspberry Pi:
   ```bash
   ping 10.0.30.1
   ping 8.8.8.8
   ```
   - [ ] VLAN 30 connectivity verified

4. **Test VLAN 40 (Storage)**
   - From UNRAID console:
   ```bash
   ping 10.0.40.1
   ping 8.8.8.8
   curl -sI https://twingate.com | head -1
   ```
   - [ ] VLAN 40 connectivity verified

5. **Test VLAN 50 (IoT/Wireless)**
   - From a wireless device:
   ```bash
   # Check IP assignment
   # Should be 10.0.50.x
   
   # Internet test
   ping 8.8.8.8
   ```
   - [ ] VLAN 50 connectivity verified

---

## 6.2 Inter-VLAN Isolation Tests

### Step-by-Step Instructions:

1. **Test IoT isolation**
   - From a device on VLAN 50 (IoT):
   ```bash
   # These should FAIL (timeout or "host unreachable")
   ping -c 3 -W 2 10.0.20.10   # K8s controller
   ping -c 3 -W 2 10.0.40.3    # NAS
   ping -c 3 -W 2 10.0.0.2    # Switch management
   
   # This should SUCCEED
   ping -c 3 8.8.8.8           # Internet
   ```
   - [ ] IoT VLAN properly isolated

2. **Test K8s to Storage connectivity**
   - From a K8s node:
   ```bash
   # This should SUCCEED (storage allowed)
   ping -c 3 10.0.40.3
   
   # Test NFS access
   showmount -e 10.0.40.3
   
   # Test SMB access
   smbclient -L 10.0.40.3 -N
   ```
   - [ ] K8s to Storage connectivity verified

4. **Test Management access**
   - From a device on VLAN 10:
   ```bash
   # Management should access everything
   ping 10.0.20.10   # K8s - should work
   ping 10.0.40.3    # NAS - should work
   ping 10.0.50.1    # IoT - should work
   ```
   - [ ] Management full access verified

---

## 6.3 Kubernetes Cluster Health

### Step-by-Step Instructions:

1. **Verify all nodes**
   ```bash
   kubectl get nodes -o wide
   
   # All nodes should show:
   # STATUS: Ready
   # IPs in 10.0.20.x range
   ```
   - [ ] All 11 nodes showing "Ready"

2. **Check system pods**
   ```bash
   kubectl get pods -n kube-system
   
   # All pods should be Running or Completed
   ```
   - [ ] All kube-system pods healthy

3. **Check all namespaces**
   ```bash
   kubectl get pods -A | grep -v Running | grep -v Completed
   
   # Should return only header or empty
   ```
   - [ ] No pods in error state

4. **Verify services**
   ```bash
   kubectl get svc -A
   
   # Verify ClusterIP and external services are assigned
   ```
   - [ ] All services have endpoints

5. **Check ingress**
   ```bash
   kubectl get ingress -A
   
   # Verify ingress resources are present
   ```
   - [ ] Ingress resources configured

---

## 6.4 Twingate Verification

### Step-by-Step Instructions:

1. **Local verification**
   - [ ] **[HUMAN ACTION]** SSH to UNRAID (10.0.40.3)
   ```bash
   # Check Twingate containers
   docker ps | grep twingate
   
   # Both connectors should show "Up"
   ```

2. **Remote verification**
   - [ ] **[HUMAN ACTION]** From a REMOTE device (outside network):
     1. Open Twingate client
     2. Connect to "Geek Network"
     3. Try accessing each of these resources:
        - ArgoCD (internal)
        - Gitea (internal)
        - Any K8s internal service
   - [ ] Remote Twingate access verified

3. **Admin console check**
   - [ ] **[HUMAN ACTION]** Login to https://admin.twingate.com
   - [ ] **[HUMAN ACTION]** Go to `Network` → `Connectors`
   - Verify both connectors show:
     - Status: Online (green)
     - Last seen: within last few minutes
   - [ ] Twingate admin console shows healthy connectors

---

## 6.5 Application Accessibility

### Step-by-Step Instructions:

1. **Test each critical application**

   **ArgoCD:**
   ```bash
   curl -sI https://argocd.eaglepass.io | head -1
   # Expected: HTTP/2 200 or similar
   ```
   - [ ] ArgoCD accessible

   **Gitea:**
   ```bash
   curl -sI https://git.eaglepass.io | head -1
   ```
   - [ ] Gitea accessible

   **Grafana:**
   ```bash
   curl -sI https://grafana.eaglepass.io | head -1
   ```
   - [ ] Grafana accessible

   **Emby:**
   ```bash
   curl -sI https://emby.eaglepass.io | head -1
   ```
   - [ ] Emby accessible

   **OpenWebUI:**
   ```bash
   curl -sI https://openwebui.eaglepass.io | head -1
   ```
   - [ ] OpenWebUI accessible

2. **Browser verification**
   - [ ] **[HUMAN ACTION]** Open each URL in browser
   - [ ] **[HUMAN ACTION]** Login to each application to verify full functionality

> [!IMPORTANT]
> **Checkpoint**: All verification tests passed. Proceed to documentation.

---
