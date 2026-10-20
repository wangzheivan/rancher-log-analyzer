#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${IMAGE_TAG:?Set IMAGE_TAG to a unique build tag}"
: "${IMAGE_REPOSITORY:?Set IMAGE_REPOSITORY to your registry/project/image}"
: "${KUBE_CONTEXT:?Set KUBE_CONTEXT explicitly to the deployment context}"
export KUBE_CONTEXT
current_context=$(kubectl config current-context)
if [[ "$current_context" != "$KUBE_CONTEXT" ]]; then
  echo 'Current kubectl context does not match KUBE_CONTEXT. Select the intended context explicitly.' >&2
  exit 1
fi
python3 scripts/check-deployment.py

docker build --tag "${IMAGE_REPOSITORY}:${IMAGE_TAG}" .
docker push "${IMAGE_REPOSITORY}:${IMAGE_TAG}"
helm upgrade --install rancher-log-analyzer charts/rancher-log-analyzer \
  --kube-context "$KUBE_CONTEXT" --namespace rancher-log-analyzer --create-namespace \
  --set-string "image.repository=${IMAGE_REPOSITORY}" \
  --set-string "image.tag=${IMAGE_TAG}" --wait --timeout 180s "$@"
kubectl --context "$KUBE_CONTEXT" --namespace rancher-log-analyzer rollout status deployment/rancher-log-analyzer --timeout=180s
kubectl --context "$KUBE_CONTEXT" --namespace rancher-log-analyzer get deployment rancher-log-analyzer -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
