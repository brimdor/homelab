#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../../.."

CHART_DIR="apps/searxng"
OUT_DIR="reports/searxng/tests"

mkdir -p "$OUT_DIR"

echo "[helm] dependency update"
helm dependency update "$CHART_DIR" | tee "$OUT_DIR/helm-dependency.txt"

echo "[helm] lint"
helm lint "$CHART_DIR" | tee "$OUT_DIR/helm-lint.txt"

echo "[helm] template (base)"
helm template searxng "$CHART_DIR" | tee "$OUT_DIR/helm-template.txt"

if [[ -f "$OUT_DIR/values.enable-backups.yaml" ]]; then
  echo "[helm] template (backups enabled)"
  helm template searxng "$CHART_DIR" -f "$OUT_DIR/values.enable-backups.yaml" | tee "$OUT_DIR/helm-template-backups.txt"
fi

echo "[done] Helm checks complete. Artifacts in $OUT_DIR"
