#!/usr/bin/env bash
set -euo pipefail

set -a
# shellcheck disable=SC1091
source .env
set +a
export GROQ_API_KEY=${GROQ_API_KEY:-${groq:-}}
export SOLACE_USERNAME=${SOLACE_USERNAME:-admin}
if [[ -z "${SOLACE_PASSWORD:-}" ]]; then
  SOLACE_PASSWORD=$(kubectl get secret sam-solace-agent-mesh-core-secrets -n sam-fx -o jsonpath='{.data.SOLACE_BROKER_PASSWORD}' | base64 -d)
  export SOLACE_PASSWORD
fi

sam config plan -m sam-config/manifest.yaml
sam config apply -m sam-config/manifest.yaml
sam config plan -m sam-config/manifest.yaml
