#!/usr/bin/env bash
set -euo pipefail

required=(aws terraform kubectl helm docker envsubst python3 sam curl)
for command_name in "${required[@]}"; do
  command -v "$command_name" >/dev/null || { echo "Missing required command: $command_name" >&2; exit 1; }
done

[[ -f .env ]] || { echo "Create .env from .env.example first." >&2; exit 1; }
set -a
# shellcheck disable=SC1091
source .env
set +a
export GROQ_API_KEY=${GROQ_API_KEY:-${groq:-}}
export JEV_API_KEY=${JEV_API_KEY:-${jev:-}}
for name in GROQ_API_KEY JEV_API_KEY; do
  [[ -n "${!name:-}" ]] || { echo "$name is required in .env" >&2; exit 1; }
done

aws sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output table
terraform -chdir=infra/aws fmt -check -recursive
terraform -chdir=infra/aws validate
python3 -m compileall -q src
printf 'Preflight passed. No credentials were printed.\n'
