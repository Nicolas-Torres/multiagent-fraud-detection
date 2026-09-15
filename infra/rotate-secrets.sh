#!/usr/bin/env bash
# Rotación de secretos compartidos entre infra/azure e infra/gcp (ADR-0023).
#
#   infra/rotate-secrets.sh plan     # terraform plan en las dos nubes, no cambia nada
#   infra/rotate-secrets.sh apply    # aplica el plan que dejó el paso anterior
#
# Antes de usarlo: copiá infra/shared.secrets.tfvars.example a
# infra/shared.secrets.tfvars y completalo con un editor de texto normal —
# nunca lo tipees en el chat ni en un comando `!`.
#
# Detecta sola la imagen que ya está corriendo en cada nube (no usa el
# default de cada variables.tf, que CD deja desactualizado en cada deploy
# — ver docs/incidentes/0001) para que un `plan` de rotación no traiga de
# arrastre un cambio de imagen no pedido.

set -euo pipefail

CMD="${1:-}"
if [[ "$CMD" != "plan" && "$CMD" != "apply" ]]; then
  echo "uso: $0 plan|apply" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHARED_VARS="$ROOT/shared.secrets.tfvars"

if [[ ! -f "$SHARED_VARS" ]]; then
  echo "falta $SHARED_VARS — copiá shared.secrets.tfvars.example y completalo a mano (no por acá)" >&2
  exit 2
fi

run_azure() {
  local plan="$ROOT/azure/rotate-secrets.tfplan"
  if [[ "$CMD" == "plan" ]]; then
    local image
    image=$(az containerapp show --name ca-fraud-detection-api --resource-group rg-fraud-detection \
      --query "properties.template.containers[0].image" -o tsv)
    echo "azure: imagen actual = $image"
    (cd "$ROOT/azure" && terraform plan -var-file="$SHARED_VARS" -var="image=$image" -out="$plan")
  else
    if [[ ! -f "$plan" ]]; then
      echo "falta $plan — corré '$0 plan' primero" >&2
      return 2
    fi
    (cd "$ROOT/azure" && terraform apply "$plan")
    rm -f "$plan"
  fi
}

run_gcp() {
  local plan="$ROOT/gcp/rotate-secrets.tfplan"
  if [[ "$CMD" == "plan" ]]; then
    local image_tag
    image_tag=$(gcloud run services describe fraud-detection-api --region us-central1 \
      --project fraud-detection-portafolio \
      --format="value(spec.template.spec.containers[0].image)" | sed 's/.*://')
    echo "gcp: tag actual = $image_tag"
    (cd "$ROOT/gcp" && terraform plan -var-file="$SHARED_VARS" -var="image_tag=$image_tag" -out="$plan")
  else
    if [[ ! -f "$plan" ]]; then
      echo "falta $plan — corré '$0 plan' primero" >&2
      return 2
    fi
    (cd "$ROOT/gcp" && terraform apply "$plan")
    rm -f "$plan"
  fi
}

echo "=== azure ==="
run_azure
echo
echo "=== gcp ==="
run_gcp
