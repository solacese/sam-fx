#!/usr/bin/env bash
# Update only the existing dashboard. Does not provision a cluster or change API access.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
: "${FX_IMAGE:?Set FX_IMAGE to the tested ECR image, preferably by digest}"
CTX=${KUBE_CONTEXT:-arn:aws:eks:eu-south-1:928672620016:cluster/sam-fx}
NS=sam-fx
mkdir -p .generated
chmod 700 .generated
umask 077
kubectl --context "$CTX" -n "$NS" get deployment fx-regime -o json > .generated/fx-regime-before-update.json
python3 - <<'PY'
import json, os
from pathlib import Path
old=json.loads(Path('.generated/fx-regime-before-update.json').read_text())
assert old['spec']['replicas']==1, 'SQLite journal requires one replica'
patch={'spec':{'strategy':{'type':'Recreate','rollingUpdate':None},'template':{'spec':{
    'securityContext':{'fsGroup':10001},
    'volumes':[{'name':'incident-journal','persistentVolumeClaim':{'claimName':'fx-incident-journal'}}],
    'containers':[{'name':'app','image':os.environ['FX_IMAGE'],
        'env':[{'name':'INCIDENT_STORE_PATH','value':'/var/lib/fx-regime/incidents.sqlite3'},
               {'name':'ENABLE_EXTERNAL_PROVIDERS','value':'false'}],
        'volumeMounts':[{'name':'incident-journal','mountPath':'/var/lib/fx-regime'}]}]
}}}}
Path('.generated/fx-regime-update.json').write_text(json.dumps(patch))
PY
kubectl --context "$CTX" apply -f deploy/k8s/base/incident-journal.yaml
kubectl --context "$CTX" -n "$NS" patch deployment fx-regime --type strategic --patch-file .generated/fx-regime-update.json
kubectl --context "$CTX" -n "$NS" rollout status deployment/fx-regime --timeout=5m
curl --fail --silent --show-error --max-time 20 https://fx.sol-se-emea.com/healthz
printf '\nDashboard rollout complete. Existing provider secrets and broker settings retained.\n'
