#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT"
set -a
# shellcheck disable=SC1091
source .env
set +a
export GROQ_API_KEY=${GROQ_API_KEY:-${groq:-}}
export JEV_API_KEY=${JEV_API_KEY:-${jev:-}}

REGION=${AWS_REGION:-eu-south-1}
CLUSTER=${CLUSTER_NAME:-sam-fx}
NAMESPACE=sam-fx
CHART=${SAM_CHART:-$ROOT/deploy/charts/solace-agent-mesh-2.1.212.tar.gz}
PULL_SECRET=${SAM_PULL_SECRET:-$ROOT/samcloudexperimental-aws-us-east-1-prod-pull-secret (2).yaml}
IMAGE_TAG=${IMAGE_TAG:-$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)-$(date +%H%M%S)}

"$ROOT/deploy/scripts/preflight.sh"
terraform -chdir=infra/aws apply -auto-approve
aws eks update-kubeconfig --region "$REGION" --name "$CLUSTER"
kubectl apply -f deploy/k8s/base/namespace.yaml

kubectl create secret generic fx-provider-secrets -n "$NAMESPACE" \
  --from-literal=GROQ_API_KEY="$GROQ_API_KEY" \
  --from-literal=JEV_API_KEY="$JEV_API_KEY" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -n "$NAMESPACE" -f "$PULL_SECRET"
kubectl apply -f deploy/k8s/base/storageclass.yaml
kubectl apply -f deploy/k8s/base/incident-journal.yaml

REPOSITORY=$(terraform -chdir=infra/aws output -raw ecr_repository_url)
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${REPOSITORY%%/*}"
docker buildx build --platform linux/amd64 -t "$REPOSITORY:$IMAGE_TAG" --push .

CERTIFICATE_ARN=$(terraform -chdir=infra/aws output -raw certificate_arn)
export CERTIFICATE_ARN
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx --force-update
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --version 4.15.1 --namespace ingress-nginx --create-namespace \
  -f <(envsubst '${CERTIFICATE_ARN}' < deploy/helm/ingress-values.yaml) --wait --timeout 5m

NLB=""
for _ in {1..60}; do
  NLB=$(kubectl get service ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].hostname}')
  [[ -n "$NLB" ]] && break
  sleep 5
done
[[ -n "$NLB" ]] || { echo "Ingress load balancer was not assigned" >&2; exit 1; }
ZONE=$(terraform -chdir=infra/aws output -raw hosted_zone_id)
for host in fx.sol-se-emea.com mesh.fx.sol-se-emea.com; do
  change_batch=$(printf '{"Changes":[{"Action":"UPSERT","ResourceRecordSet":{"Name":"%s","Type":"CNAME","TTL":60,"ResourceRecords":[{"Value":"%s"}]}}]}' "$host" "$NLB")
  aws route53 change-resource-record-sets --hosted-zone-id "$ZONE" \
    --change-batch "$change_batch" >/dev/null
done

mkdir -p .generated
chmod 700 .generated
if ! kubectl get secret external-tls-terminated-at-nlb -n "$NAMESPACE" >/dev/null 2>&1; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
    -keyout .generated/internal-tls.key -out .generated/internal-tls.crt \
    -subj '/CN=mesh.fx.sol-se-emea.com' >/dev/null 2>&1
  kubectl create secret tls external-tls-terminated-at-nlb -n "$NAMESPACE" \
    --cert=.generated/internal-tls.crt --key=.generated/internal-tls.key
fi

export GROQ_API_KEY
envsubst < deploy/helm/sam-values.yaml > .generated/sam-values.yaml
helm upgrade --install sam "$CHART" --namespace "$NAMESPACE" \
  -f .generated/sam-values.yaml --wait --timeout 15m

FX_IMAGE="$REPOSITORY:$IMAGE_TAG" envsubst < deploy/k8s/base/app.yaml | kubectl apply -f -
kubectl rollout status deployment/fx-regime -n "$NAMESPACE" --timeout=5m

"$ROOT/deploy/scripts/verify.sh"
printf 'FX demo deployed at https://fx.sol-se-emea.com\n'
