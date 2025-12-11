#!/bin/bash
# Homelab Reconnaissance Script
# Generated: 2025-12-10

export KUBECONFIG=/homelab/metal/kubeconfig.yaml

echo "========================================="
echo "METAL LAYER - Hardware & OS"
echo "========================================="
echo ""

echo "=== NODE STATUS ==="
kubectl get nodes -o wide 2>&1 || echo "ERROR: Could not get nodes"
echo ""

echo "=== NODE RESOURCE USAGE ==="
kubectl top nodes 2>&1 || echo "WARNING: Metrics server may not be available"
echo ""

echo "=== NODE CONDITIONS ==="
kubectl describe nodes 2>&1 | grep -A 5 "Conditions:"
echo ""

echo "========================================="
echo "SYSTEM LAYER - Kubernetes Core"
echo "========================================="
echo ""

echo "=== SYSTEM PODS ==="
kubectl get pods -n kube-system --sort-by='.status.containerStatuses[0].restartCount' 2>&1
echo ""

echo "=== CILIUM STATUS ==="
kubectl get pods -n kube-system -l k8s-app=cilium 2>&1
echo ""

echo "=== ROOK-CEPH PODS ==="
kubectl get pods -n rook-ceph 2>&1
echo ""

echo "=== CEPH STATUS ==="
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph status 2>&1 || echo "ERROR: Could not get Ceph status"
echo ""

echo "=== CEPH HEALTH ==="
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph health detail 2>&1 || echo "ERROR: Could not get Ceph health"
echo ""

echo "=== STORAGE CLASSES ==="
kubectl get storageclass 2>&1
echo ""

echo "=== PERSISTENT VOLUMES ==="
kubectl get pv 2>&1
echo ""

echo "========================================="
echo "PLATFORM LAYER - Middleware"
echo "========================================="
echo ""

echo "=== ARGOCD PODS ==="
kubectl get pods -n argocd 2>&1
echo ""

echo "=== ARGOCD APPLICATIONS ==="
kubectl get applications -n argocd 2>&1
echo ""

echo "=== ARGOCD SYNC STATUS ==="
kubectl get applications -n argocd -o json 2>&1 | jq -r '.items[] | "\(.metadata.name): \(.status.sync.status) - \(.status.health.status)"' 2>&1 || echo "jq not available"
echo ""

echo "=== INGRESS CONTROLLER ==="
kubectl get pods -n ingress-nginx 2>&1
echo ""

echo "=== INGRESS RESOURCES ==="
kubectl get ingress --all-namespaces 2>&1
echo ""

echo "=== CERT-MANAGER ==="
kubectl get pods -n cert-manager 2>&1
echo ""

echo "=== CERTIFICATES ==="
kubectl get certificates --all-namespaces 2>&1
echo ""

echo "=== MONITORING PODS ==="
kubectl get pods -n monitoring-system 2>&1 || kubectl get pods -n monitoring 2>&1 || echo "No monitoring namespace found"
echo ""

echo "========================================="
echo "APPS LAYER - User Services"
echo "========================================="
echo ""

echo "=== APPLICATION NAMESPACES ==="
kubectl get ns | grep -E 'emby|gitea|sonarr|radarr|ollama|openwebui|sabnzbd|searxng' 2>&1
echo ""

for ns in emby gitea sonarr radarr ollama openwebui sabnzbd searxng; do
  echo "=== $ns PODS ==="
  kubectl get pods -n $ns 2>&1 || echo "Namespace $ns not found"
  echo ""
done

echo "=== TOP PODS BY MEMORY ==="
kubectl top pods --all-namespaces --sort-by=memory 2>&1 | head -20
echo ""

echo "=== TOP PODS BY CPU ==="
kubectl top pods --all-namespaces --sort-by=cpu 2>&1 | head -20
echo ""

echo "========================================="
echo "RECONNAISSANCE COMPLETE"
echo "========================================="
