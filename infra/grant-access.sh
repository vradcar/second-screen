#!/usr/bin/env bash
# Give the signed-in user the "Foundry User" role on the Foundry resource, so the
# agents can authenticate with `az login` (no API keys). Run in Cloud Shell.
#   RESOURCE=secondscreen-ai-ae9ze bash grant-access.sh
set -euo pipefail
RG="${RG:-rg-second-screen}"
RESOURCE="${RESOURCE:?set RESOURCE to your Foundry resource name}"
FOUNDRY_USER_ROLE="53ca6127-db72-4b80-b1b0-d745d6d5456d"   # Foundry User (formerly Azure AI User)

ME=$(az ad signed-in-user show --query id -o tsv)
SCOPE=$(az cognitiveservices account show -n "$RESOURCE" -g "$RG" --query id -o tsv)
az role assignment create --role "$FOUNDRY_USER_ROLE" --assignee-object-id "$ME" \
  --assignee-principal-type User --scope "$SCOPE" -o none
echo "Granted Foundry User on $RESOURCE. Role assignments can take a few minutes to apply."
