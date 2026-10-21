#!/usr/bin/env bash
# Create the Foundry resource, project and model deployment for Second Screen.
# Run in Azure Cloud Shell (Bash):  bash setup-foundry.sh
# Override defaults with env vars, e.g.  LOCATION=swedencentral bash setup-foundry.sh
set -euo pipefail

LOCATION="${LOCATION:-eastus2}"
RG="${RG:-rg-second-screen}"
SUFFIX="${SUFFIX:-$(tr -dc 'a-z0-9' </dev/urandom | head -c 5)}"
RESOURCE="${RESOURCE:-secondscreen-ai-$SUFFIX}"
PROJECT="${PROJECT:-second-screen}"
MODEL="${MODEL:-gpt-4.1-mini}"
MODEL_VERSION="${MODEL_VERSION:-2025-04-14}"
CAPACITY="${CAPACITY:-30}"   # thousands of tokens per minute

echo "==> Registering provider (no-op if already registered)"
az provider register --namespace Microsoft.CognitiveServices --wait

echo "==> Resource group $RG in $LOCATION"
az group create --name "$RG" --location "$LOCATION" --tags project=second-screen -o none

echo "==> Foundry resource $RESOURCE"
az cognitiveservices account create \
  --name "$RESOURCE" --resource-group "$RG" --location "$LOCATION" \
  --kind AIServices --sku S0 --custom-domain "$RESOURCE" \
  --assign-identity --allow-project-management true --yes -o none

echo "==> Foundry project $PROJECT"
az cognitiveservices account project create \
  --name "$RESOURCE" --resource-group "$RG" --location "$LOCATION" \
  --project-name "$PROJECT" -o none

echo "==> Deploying $MODEL ($MODEL_VERSION), ${CAPACITY}K TPM"
az cognitiveservices account deployment create \
  --name "$RESOURCE" --resource-group "$RG" \
  --deployment-name "$MODEL" --model-name "$MODEL" --model-version "$MODEL_VERSION" \
  --model-format OpenAI --sku-name GlobalStandard --sku-capacity "$CAPACITY" -o none

PROJECT_ENDPOINT=$(az cognitiveservices account project show \
  --name "$RESOURCE" --resource-group "$RG" --project-name "$PROJECT" \
  --query 'properties.endpoints."AI Foundry API"' -o tsv)

cat <<OUT

Done. Put these in your .env (never commit it):

AZURE_AI_PROJECT_ENDPOINT=$PROJECT_ENDPOINT
AZURE_OPENAI_ENDPOINT=https://$RESOURCE.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=$MODEL
AZURE_RESOURCE_GROUP=$RG
AZURE_FOUNDRY_RESOURCE=$RESOURCE

API key (only if you're not using 'az login' / Entra auth):
  az cognitiveservices account keys list -n $RESOURCE -g $RG --query key1 -o tsv
OUT
