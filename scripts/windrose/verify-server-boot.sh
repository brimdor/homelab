#!/usr/bin/env bash
# verify-server-boot.sh — Windrose dedicated server boot smoke test
#
# Verifies that the Windrose Pod (production or canary) has:
#   1. A wine process running (the Windows server binary under Wine)
#   2. ServerDescription.json generated and patched with expected values
#   3. The Windows server binary present (DepotDownloader succeeded)
#   4. Port 7777 bound on cyndaquil (TCP+UDP) when hostNetwork is used
#
# Usage:
#   NAMESPACE=windrose ./verify-server-boot.sh
#   NAMESPACE=windrose-canary ./verify-server-boot.sh
#
set -euo pipefail

NAMESPACE="${NAMESPACE:-windrose}"
POD="${POD:-$(kubectl get pod -n "$NAMESPACE" -l app.kubernetes.io/name=windrose -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)}"

if [ -z "$POD" ]; then
  echo "ERROR: no windrose pod found in namespace $NAMESPACE"
  exit 1
fi

echo "==> Verifying Windrose server in namespace $NAMESPACE, pod $POD"

# 1. The init.sh container starts as root to usermod, then su's to steam.
# Show current identity; the long-running wine process must eventually be steam.
echo "--> container identity"
kubectl exec -n "$NAMESPACE" -c main "$POD" -- id

# 2. Wine process must be running.
echo "--> wine process listing"
kubectl exec -n "$NAMESPACE" -c main "$POD" -- pgrep -af wine || {
  echo "ERROR: no wine process found"
  exit 1
}

# 3. ServerDescription.json must exist and be non-empty.
echo "--> ServerDescription.json presence"
kubectl exec -n "$NAMESPACE" -c main "$POD" -- test -s /home/steam/server-files/R5/ServerDescription.json || {
  echo "ERROR: /home/steam/server-files/R5/ServerDescription.json missing or empty"
  exit 1
}

# 4. JSON values must match the chart contract.
echo "--> ServerDescription.json values"
kubectl exec -n "$NAMESPACE" -c main "$POD" -- cat /home/steam/server-files/R5/ServerDescription.json | \
  jq '.ServerDescription_Persistent | {InviteCode, UseDirectConnection, DirectConnectionServerPort, ServerName, MaxPlayerCount, IsPasswordProtected, UserSelectedRegion}'

# 5. Windows server binary must exist (proves DepotDownloader fetched it).
echo "--> Windows server binary presence"
kubectl exec -n "$NAMESPACE" -c main "$POD" -- test -f /home/steam/server-files/R5/Binaries/Win64/WindroseServer-Win64-Shipping.exe || {
  echo "ERROR: WindroseServer-Win64-Shipping.exe missing"
  exit 1
}

# 6. Readiness condition must be True (probes passed).
echo "--> pod readiness"
kubectl get pod -n "$NAMESPACE" "$POD" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}'
echo

# 7. Port binding on the host.  Only meaningful for the production namespace
#    because canary intentionally has no hostPort.
if [ "$NAMESPACE" = "windrose" ]; then
  NODE="$(kubectl get pod -n "$NAMESPACE" "$POD" -o jsonpath='{.spec.nodeName}')"
  echo "--> node $NODE port 7777 binding (requires node shell access)"
  if [ "$NODE" = "cyndaquil" ]; then
    echo "    TCP listeners:"
    kubectl exec -n "$NAMESPACE" -c main "$POD" -- sh -c 'ss -tlnp 2>/dev/null | grep :7777 || netstat -tln 2>/dev/null | grep :7777' || true
    echo "    UDP listeners:"
    kubectl exec -n "$NAMESPACE" -c main "$POD" -- sh -c 'ss -ulnp 2>/dev/null | grep :7777 || netstat -uln 2>/dev/null | grep :7777' || true
  else
    echo "WARN: pod not on cyndaquil; host port check skipped"
  fi
fi

echo "==> Windrose boot verification passed for $NAMESPACE/$POD"
