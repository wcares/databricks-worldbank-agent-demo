#!/usr/bin/env bash
# Deploys the Databricks chat UI template (databricks/app-templates, e2e-chatbot-app-next) as a
# Databricks App pointed at our agent's serving endpoint. The template is fetched at a pinned commit
# into .build/ (git-ignored) rather than copied into this repo: it is a separate project with its own
# licence. It runs in ephemeral mode (chat history in memory, no Lakebase database).
# Usage: scripts/deploy_chat_app.sh <serving_endpoint_name>
set -euo pipefail
ENDPOINT=${1:?usage: $0 <serving_endpoint_name>}
REPO=https://github.com/databricks/app-templates.git
PIN=0e572976459aafa3d41047067382cb9a6c015d52   # 2026-10-16
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIR="$ROOT/.build/app-templates"

if [ ! -d "$DIR/.git" ]; then
  git clone --filter=blob:none --no-checkout -q "$REPO" "$DIR"
  git -C "$DIR" sparse-checkout set e2e-chatbot-app-next
fi
git -C "$DIR" fetch -q origin "$PIN"
git -C "$DIR" checkout -q "$PIN"

cd "$DIR/e2e-chatbot-app-next"
databricks bundle deploy -t dev --var serving_endpoint_name="$ENDPOINT"
databricks bundle run databricks_chatbot -t dev --var serving_endpoint_name="$ENDPOINT"
databricks bundle summary -t dev --var serving_endpoint_name="$ENDPOINT" | grep -iE "url|name"
