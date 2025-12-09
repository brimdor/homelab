---
description: Troubleshoot an issue in the homelab Kubernetes cluster by connecting to the controller, analyzing the problem, and implementing fixes.
---

## User Input

```text
$ARGUMENTS
```

The user will describe the issue they are experiencing. Use this description to guide your investigation.

---

# Troubleshoot Homelab Kubernetes Cluster

This workflow guides the agent through connecting to the homelab controller and systematically troubleshooting issues in the Kubernetes cluster.

## Available Resources

1. **Browser** - Access to apps in the cluster for visual verification
2. **Terminal** - SSH access to the controller (10.0.50.120)
3. **Kubernetes Cluster** - Full kubectl access via the controller
4. **Codebase** - https://github.com/brimdor/homelab or https://git.eaglepass.io

## Execution Principles

- **Be methodical:** Gather information before making changes
- **Document findings:** Keep track of what you discover
- **Verify fixes:** Always confirm the issue is resolved after applying changes
- **Minimize disruption:** Prefer targeted fixes over broad restarts

Output format for phase transitions:

```
## Phase N: [Phase Name]
[Execute phase work directly]
```

---

## Phase 1: Connect to Controller

### 1.1 Establish SSH Connection

Connect to the homelab controller:

// turbo
```bash
ssh brimdor@10.0.50.120
```

**Wait for the connection to be established before proceeding.**

### 1.2 Navigate to Homelab Directory

// turbo
```bash
cd homelab
```

### 1.3 Initialize Tools Environment

// turbo
```bash
make tools
```

**Wait for the tools environment to fully initialize.** You will see a bash prompt when ready.

### 1.4 Output Connection Summary

```
## Phase 1: Connection Complete

✓ Connected to controller at 10.0.50.120
✓ Homelab directory accessed
✓ Tools environment initialized and ready

**Status:** Ready to begin troubleshooting
```

---

## Phase 2: Initial Assessment

### 2.1 Gather Cluster Overview

Collect general cluster health information:

```bash
# Check node status
kubectl get nodes -o wide

# Check all pods across namespaces
kubectl get pods -A | grep -v Running | grep -v Completed

# Check recent events
kubectl get events -A --sort-by='.metadata.creationTimestamp' | tail -20
```

### 2.2 Identify Problem Area

Based on the user's issue description and initial assessment:

1. **Determine affected namespace(s)**
2. **Identify affected workload(s)** (deployments, statefulsets, daemonsets)
3. **Note any error patterns** in pods or events

### 2.3 Targeted Investigation

For the affected resources, gather detailed information:

```bash
# Describe the problematic resource
kubectl describe <resource-type> <resource-name> -n <namespace>

# Check pod logs
kubectl logs <pod-name> -n <namespace> --tail=100

# Check previous container logs if pod is restarting
kubectl logs <pod-name> -n <namespace> --previous --tail=100

# Check for resource constraints
kubectl top pods -n <namespace>
kubectl top nodes
```

### 2.4 Output Assessment Summary

```
## Phase 2: Assessment Complete

### Issue Identified:
[Describe the root cause or suspected issue]

### Affected Resources:
- **Namespace:** [namespace]
- **Workload:** [workload type and name]
- **Pods:** [pod names/status]

### Error Summary:
[Key error messages or symptoms]

### Preliminary Analysis:
[Initial thoughts on the cause]
```

---

## Phase 3: Investigate Configuration

### 3.1 Check Deployed Configuration

Examine the current state in the cluster:

```bash
# Get the current deployment/statefulset configuration
kubectl get <resource-type> <resource-name> -n <namespace> -o yaml

# Check related configmaps
kubectl get configmaps -n <namespace>

# Check related secrets
kubectl get secrets -n <namespace>

# Check services and endpoints
kubectl get svc,endpoints -n <namespace>
```

### 3.2 Compare with Source Configuration

Reference the homelab codebase to compare expected vs actual configuration:

- Check `apps/<app-name>/` directory for application configuration
- Review `values.yaml` for Helm chart values
- Check for any recent changes that may have caused the issue

### 3.3 Check Dependencies

Investigate upstream dependencies:

```bash
# Check if the issue is related to a dependency
kubectl get pods -n <dependency-namespace>

# Check service connectivity
kubectl exec -it <pod-name> -n <namespace> -- curl -v <service-url>

# Check DNS resolution
kubectl exec -it <pod-name> -n <namespace> -- nslookup <service-name>
```

### 3.4 Output Investigation Summary

```
## Phase 3: Investigation Complete

### Configuration Analysis:
[Summary of configuration state]

### Dependencies Status:
[Status of related services/dependencies]

### Root Cause Identified:
[Clear description of the root cause]
```

---

## Phase 4: Develop Fix Strategy

### 4.1 Analyze Fix Options

Based on the investigation, determine the appropriate fix:

**Immediate Fixes (in-cluster):**
- Restart pods/deployments
- Scale resources
- Update configmaps/secrets
- Patch resources

**Configuration Changes (requires code change):**
- Update Helm values
- Modify application configuration
- Update resource limits/requests

### 4.2 Document Proposed Fix

```
## Phase 4: Fix Strategy

### Proposed Action:
[Describe the fix approach]

### Expected Outcome:
[What should happen after the fix]

### Rollback Plan:
[How to revert if the fix doesn't work]

### Risk Assessment:
- **Impact:** [Low/Medium/High]
- **Downtime:** [Expected downtime if any]
```

### 4.3 Request Approval (if needed)

For significant changes that could cause downtime or data loss, request user approval:

```
⚠️ This fix may cause [impact description].

**Proceed with the fix?** (Y/N)
```

---

## Phase 5: Apply Fix

### 5.1 Apply In-Cluster Fix

For immediate cluster-level fixes:

```bash
# Restart a deployment
kubectl rollout restart deployment/<name> -n <namespace>

# Scale resources
kubectl scale deployment/<name> -n <namespace> --replicas=<count>

# Patch a resource
kubectl patch <resource> <name> -n <namespace> -p '<patch>'

# Apply updated configuration
kubectl apply -f <manifest-file>
```

### 5.2 Apply Configuration Changes

For changes requiring code updates:

1. Modify the configuration files in the homelab repository
2. Commit changes with descriptive message
3. Trigger ArgoCD sync or manual deployment

```bash
# ArgoCD sync (if applicable)
argocd app sync <app-name>

# Or manually apply Helm chart
helm upgrade <release-name> <chart> -n <namespace> -f values.yaml
```

### 5.3 Output Fix Summary

```
## Phase 5: Fix Applied

### Actions Taken:
- [List of actions performed]

### Status:
[Immediate status of the fix]
```

---

## Phase 6: Verify Resolution

### 6.1 Check Resource Health

Verify the affected resources are now healthy:

```bash
# Check pod status
kubectl get pods -n <namespace> -w

# Check deployment rollout status
kubectl rollout status deployment/<name> -n <namespace>

# Check for any remaining errors
kubectl get events -n <namespace> --sort-by='.metadata.creationTimestamp' | tail -10
```

### 6.2 Verify Application Functionality

**Using the terminal:**
```bash
# Test endpoint connectivity
curl -v <application-url>

# Check logs for normal operation
kubectl logs <pod-name> -n <namespace> --tail=50
```

**Using the browser:**
If the application has a web interface, use the browser to:
- Navigate to the application URL
- Verify expected functionality
- Check for any UI errors

### 6.3 Monitor for Stability

```bash
# Watch for any recurring issues
kubectl get pods -n <namespace> -w

# Check resource utilization
kubectl top pods -n <namespace>
```

### 6.4 Output Verification Summary

```
## Phase 6: Verification Complete

### Health Check Results:
- **Pod Status:** [status]
- **Endpoint Test:** [result]
- **Application Test:** [result]

### Resolution Status:
✓ Issue resolved / ⚠️ Partially resolved / ❌ Issue persists
```

---

## Phase 7: Final Summary

### 7.1 Document Resolution

```
## Troubleshooting Complete

### Original Issue:
[User's reported issue]

### Root Cause:
[What caused the issue]

### Resolution:
[How it was fixed]

### Actions Taken:
1. [Action 1]
2. [Action 2]
...

### Verification:
[Confirmation that the issue is resolved]

### Recommendations:
[Any preventive measures or follow-up actions]
```

---

## Error Handling

### Connection Errors

If unable to connect to the controller:

```
❌ Error: Unable to SSH to controller at 10.0.50.120

**Possible causes:**
- Network connectivity issue
- SSH service not running
- Invalid credentials

**Suggested actions:**
1. Verify network connectivity
2. Check if controller is powered on
3. Verify SSH credentials
```

### Kubernetes Access Errors

If kubectl commands fail:

```
❌ Error: Unable to access Kubernetes cluster

**Possible causes:**
- kubeconfig not configured
- Cluster unreachable
- Authentication expired

**Suggested actions:**
1. Check kubeconfig
2. Verify cluster connectivity
3. Re-authenticate if needed
```

### Fix Application Errors

If the fix fails to apply:

```
❌ Error: Fix failed to apply

**Error message:** [error details]

**Rollback steps:**
[Steps to revert any partial changes]

**Alternative approaches:**
[Other ways to address the issue]
```

---

## Appendix: Common Troubleshooting Commands

### Pod Issues

```bash
# Get detailed pod info
kubectl describe pod <pod-name> -n <namespace>

# Get pod logs
kubectl logs <pod-name> -n <namespace> -f

# Get logs from previous container
kubectl logs <pod-name> -n <namespace> --previous

# Execute into a pod
kubectl exec -it <pod-name> -n <namespace> -- /bin/sh
```

### Networking Issues

```bash
# Check service endpoints
kubectl get endpoints <service-name> -n <namespace>

# Test DNS resolution
kubectl run -it --rm debug --image=busybox --restart=Never -- nslookup <service-name>

# Test connectivity
kubectl run -it --rm debug --image=curlimages/curl --restart=Never -- curl -v <url>
```

### Storage Issues

```bash
# Check PVC status
kubectl get pvc -n <namespace>

# Describe PVC for events
kubectl describe pvc <pvc-name> -n <namespace>

# Check PV status
kubectl get pv
```

### Certificate Issues

```bash
# Check certificate secrets
kubectl get secrets -n <namespace> | grep tls

# Check certificate expiry
kubectl get certificate -n <namespace>

# Describe certificate for issues
kubectl describe certificate <cert-name> -n <namespace>
```

### ArgoCD Issues

```bash
# List all applications
argocd app list

# Get application status
argocd app get <app-name>

# Sync application
argocd app sync <app-name>

# Check application diff
argocd app diff <app-name>
```