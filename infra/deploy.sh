#!/usr/bin/env bash
# Deploy Second Screen to Azure. Run in Azure Cloud Shell (Bash) from the repo root:
#   git clone https://github.com/vradcar/second-screen && cd second-screen
#   FOUNDRY=secondscreen-ai-ae9ze AGENTS=live bash infra/deploy.sh
# AGENTS=live: every broadcast runs the agents (and commentator) live on Foundry.
set -euo pipefail

RG="${RG:-rg-second-screen}"
LOCATION="${LOCATION:-eastus}"
FOUNDRY="${FOUNDRY:?set FOUNDRY to your Foundry resource name, e.g. secondscreen-ai-ae9ze}"
OWNER="${OWNER:-vradcar}"
IMAGE="${IMAGE:-ghcr.io/${OWNER}/second-screen:latest}"
AGENTS="${AGENTS:-recorded}"
TTS="${TTS:-}"   # gpt-4o-mini-tts deployment name, if you made one
TOKEN="${TOKEN:-$(cut -c1-12 /proc/sys/kernel/random/uuid)}"

echo "==> Registering resource providers (first run only takes a minute)"
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.Insights Microsoft.EventHub Microsoft.DocumentDB; do
  az provider register --namespace "$ns" -o none
done

echo "==> Deploying to $RG ($LOCATION): Container Apps, Event Hubs, Cosmos DB, App Insights"
OUT=$(az deployment group create -g "$RG" -n second-screen -f infra/main.bicep \
  -p location="$LOCATION" foundryName="$FOUNDRY" image="$IMAGE" broadcastAgents="$AGENTS" startToken="$TOKEN" ttsDeployment="$TTS" \
  --query properties.outputs -o json)

URL=$(echo "$OUT" | python3 -c 'import json,sys; print(json.load(sys.stdin)["url"]["value"])')
cat <<DONE

Deployed.
  App:          $URL
  Start token:  $TOKEN   (keep this; needed to start/stop broadcasts and for live agents)

Go live (agents: $AGENTS):
  $URL/?mode=onair&speed=5&token=$TOKEN
  -> "Kick off a brand-new match", then turn Commentary on.
Share $URL/?mode=onair with viewers (no token: they can watch, not start).
DONE
