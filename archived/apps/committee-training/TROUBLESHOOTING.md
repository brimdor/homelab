# Homelab Training Troubleshooting

This document documents common issues encountered when running Committee training on the homelab Kubernetes cluster and how to resolve them.

---

## Issue 1: PVC Already Exists Error

### Error Message
```
Error from server (Invalid): error when applying patch:
PersistentVolumeClaim "committee-checkpoints" is invalid: spec is Forbidden: spec is immutable after creation except resources.requests and volumeAttributesClassName for bound claims
```

### Cause
- `job.yaml` contains PVC definitions that were already created by `manage.sh sync`
- When running `kubectl apply -f job.yaml`, it attempts to patch the existing PVCs
- Kubernetes PVCs are immutable after being bound, so patching fails

### Fix Applied
1. Split `job.yaml` into separate files:
   - `pvcs.yaml` - Contains namespace and PVC definitions (created once)
   - `job-only.yaml` - Contains ConfigMap and Job (applied multiple times)

2. Update `manage.sh` to apply `pvcs.yaml` before `job-only.yaml`

### Prevention
- Always use `manage.sh sync` to create PVCs before starting training
- PVCs are idempotent - running sync multiple times won't cause errors
- Never manually apply `job.yaml` with PVCs - use `job-only.yaml`

---

## Issue 2: Pod Stuck in Pending (Scheduling Issues)

### Error Message
```
Warning  FailedScheduling  0/10 nodes are available: 1 Insufficient cpu, 1 Insufficient memory, 1 node(s) had untolerated taint {dedicated: sprigatito}, 1 node(s) had untolerated taint {node.kubernetes.io/unreachable: }
```

### Cause
1. **Toleration Mismatch**: Job had toleration with specific `operator: "Equal"` which may not match as expected
2. **Node Overcommitment**: Arcanine node had high resource usage (91% CPU, 139% memory) when job was submitted
3. **Automatic Tolerations**: Pod was getting automatic tolerations for unreachable/not-ready nodes that weren't needed

### Fixes Applied

#### Fix 1: Update Toleration
Changed toleration in `job-only.yaml` from:
```yaml
tolerations:
  - key: "dedicated"
    operator: "Equal"
    value: "arcanine"
    effect: "NoSchedule"
```

To:
```yaml
tolerations:
  - key: "dedicated"
    operator: "Exists"
    effect: "NoSchedule"
```

This uses `operator: "Exists"` which is more flexible and matches taint by key+effect without requiring value match.

#### Fix 2: Reduce Resource Requests
Changed resource requests in `job-only.yaml` from:
```yaml
resources:
  requests:
    memory: 32Gi
    cpu: "4"
```

To:
```yaml
resources:
  requests:
    memory: 24Gi
    cpu: "2"
```

This makes the job request less resources, increasing chance of fitting on busy nodes.

### Prevention
1. Check node resource usage before starting training:
   ```bash
   kubectl describe nodes arcanine | grep -A10 "Allocated resources"
   ```

2. If node is highly committed (>80% CPU/memory), consider:
   - Scaling down other workloads on Arcanine
   - Using even lower resource requests
   - Waiting for node to free up resources

3. Always use `manage.sh start` which automatically scales down conflicting services (Ollama, LocalAI) before starting training.

---

## Issue 3: Arcanine Node Taint

### Node Information
Arcanine node has taint:
```yaml
Taints: dedicated=arcanine:NoSchedule
```

Labels:
```yaml
kubernetes.io/hostname: arcanine
```

### Toleration Requirements
To schedule on Arcanine, pod must have toleration:
```yaml
tolerations:
  - key: "dedicated"
    operator: "Exists"  # OR "Equal" with value: "arcanine"
    effect: "NoSchedule"
```

And node affinity:
```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/hostname
              operator: In
              values:
                - "arcanine"
```

### Why Fix Was Needed
The original toleration used `operator: "Equal"` with a specific value. While technically correct, using `operator: "Exists"` is more reliable for matching taints and works with Kubernetes scheduler better.

---

## Issue 4: kubectl apply vs create

### Problem
Using `kubectl apply` on resources that should only be created once (like PVCs) causes issues because:
1. PVCs can't be modified after being bound
2. `kubectl apply` tries to patch, which conflicts with immutability
3. Multiple attempts cause confusing error messages

### Solution

Use `kubectl apply` with idempotent resources, and use `kubectl create` for non-idempotent resources. For this setup:

- **pvcs.yaml**: Contains namespace and PVCs (apply via kubectl apply - idempotent for namespace, create handles existing PVCs)
- **job-only.yaml**: Contains ConfigMap and Job (apply via kubectl apply - both are idempotent when applied repeatedly)

---

## Recovery Steps

If training job is stuck in Pending:

1. Check pod events:
   ```bash
   kubectl describe pod <pod-name> -n committee-training | grep -A20 "Events:"
   ```

2. Check node resource usage:
   ```bash
   kubectl describe nodes arcanine | grep -A10 "Allocated resources"
   ```

3. Check if conflicting services are running:
   ```bash
   kubectl get pods -n ollama
   kubectl get pods -n localai
   ```

4. Delete and retry:
   ```bash
   cd ~/Documents/GitHub/homelab/apps/committee-training
   ./manage.sh stop
   ./manage.sh start --debug
   ```

---

## File Reference

| File | Purpose | Apply Method |
|------|---------|--------------|
| `pvcs.yaml` | Namespace and PVCs (created once) | `kubectl apply -f pvcs.yaml` |
| `job-only.yaml` | ConfigMap and Job (no PVCs) | `kubectl apply -f job-only.yaml` |
| `manage.sh` | Orchestration | Uses both files in correct order |

---

## Checklist Before Training

- [ ] Run `./manage.sh sync` to ensure code is copied
- [ ] Check node has enough resources (`kubectl describe nodes arcanine`)
- [ ] Verify Ollama/LocalAI are scaled down (will happen automatically)
- [ ] Use `./manage.sh start` (not manual `kubectl apply`)

---

## Status

| Issue | Status |
|-------|--------|
| PVC Already Exists | ✅ Fixed - Split into pvcs.yaml and job-only.yaml |
| Pod Pending (Scheduling) | ✅ Fixed - Updated tolerations and reduced resource requests |
| Toleration Issues | ✅ Fixed - Changed to operator: Exists |
| Resource Overcommitment | ✅ Fixed - Reduced CPU from 4 to 2, Memory from 32Gi to 24Gi |
