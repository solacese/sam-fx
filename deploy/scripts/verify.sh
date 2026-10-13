#!/usr/bin/env bash
set -euo pipefail

NAMESPACE=${NAMESPACE:-sam-fx}
DASHBOARD=${DASHBOARD_URL:-https://fx.sol-se-emea.com}
MESH=${MESH_URL:-https://mesh.fx.sol-se-emea.com}
kubectl wait --for=condition=Ready pods --all -n "$NAMESPACE" --timeout=10m
kubectl get pods,ingress -n "$NAMESPACE"

for url in "$DASHBOARD" "$MESH"; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' "$url")
  [[ "$code" == "200" ]] || {
    echo "Expected public HTTP 200 from $url; got HTTP $code" >&2
    exit 1
  }
done

curl -fsS "$DASHBOARD/healthz" | python3 -c 'import json,sys; assert json.load(sys.stdin)["status"] == "ok"'
printf 'Public dashboard, Agent Mesh console, and health endpoint passed.\n'
