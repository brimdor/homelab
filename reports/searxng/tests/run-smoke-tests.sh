#!/usr/bin/env bash
set -euo pipefail

NS="${NS:-searxng}"
APP="${APP:-searxng}"

echo "[info] Checking Pod env from Secret"
kubectl -n "$NS" get pod -l app.kubernetes.io/name=$APP -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{range .spec.containers[*].env[*]}{.name}{"="}{.valueFrom.secretKeyRef.name}{"/"}{.valueFrom.secretKeyRef.key}{"\n"}{end}{end}' | sed 's/==\//=/g' || true

echo "[info] Service check"
SVC="$APP"
PORT=8080
kubectl -n "$NS" run curl --rm -i --restart=Never --image=curlimages/curl:8.10.1 -- \
  curl -sS -o /dev/null -w "%{http_code}\n" "http://$SVC:$PORT/" || true

echo "[info] Ingress check"
HOST="${HOST:-searxng.eaglepass.io}"
curl -sS -o /dev/null -w "%{http_code}\n" -H "Host: $HOST" "https://$HOST/" || true

echo "[done] Smoke tests attempted"
