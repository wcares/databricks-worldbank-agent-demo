#!/usr/bin/env bash
# Removes everything the demo created in the workspace. DRY RUN by default: prints what would be deleted.
# Pass --yes to actually delete. Order: app and endpoint first (they read the data), data last.
#
#   chat app                 db-chatbot-dev-<user>      (Databricks App)
#   serving endpoint         wb-insights-agent          (+ its Review App)
#   SQL alerts               "wb_demo: ..."             (3)
#   Genie space              "World Bank development data"
#   Vector Search            index wb_demo.gold.doc_chunks_index, endpoint wb_demo_vs
#   bundle resources         jobs wb_demo_pipeline, wb_agent_release, wb_agent_test, wb_ops; 2 dashboards
#   catalog                  wb_demo (all schemas, tables, volume, registered model) - DROP CATALOG CASCADE
#   MLflow experiment        /Users/<user>/wb_insights_agent
# Groups and the service principal are left in place (remove them in the workspace settings if wanted).
#
# Usage: scripts/teardown.sh [--yes] [warehouse_id]
set -uo pipefail
YES=false; [ "${1:-}" = "--yes" ] && { YES=true; shift; }
WH=${1:-33fd48ef78c8fbfa}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
USER_NAME=$(databricks current-user me -o json | python3 -c 'import sys,json;print(json.load(sys.stdin)["userName"])')
APP=$(databricks apps list -o json | python3 -c 'import sys,json;[print(a["name"]) for a in json.load(sys.stdin) if a["name"].startswith("db-chatbot-dev-")]' | head -1)
GENIE=$(databricks genie list-spaces -o json | python3 -c 'import sys,json;d=json.load(sys.stdin);d=d.get("spaces",d) if isinstance(d,dict) else d;[print(s["space_id"]) for s in d if s.get("title")=="World Bank development data"]' | head -1)
ALERTS=$(databricks alerts-v2 list-alerts -o json | python3 -c 'import sys,json;d=json.load(sys.stdin);d=d if isinstance(d,list) else d.get("alerts",[]);[print(a["id"]) for a in d if a.get("display_name","").startswith("wb_demo:")]')
EXP_ID=$(databricks api get "/api/2.0/mlflow/experiments/get-by-name?experiment_name=/Users/$USER_NAME/wb_insights_agent" 2>/dev/null | python3 -c 'import sys,json;print(json.load(sys.stdin)["experiment"]["experiment_id"])' 2>/dev/null)

step() {  # step "<description>" <command...>
  local what=$1; shift
  if $YES; then echo "DELETE  $what"; "$@" || echo "        (failed or already gone)"; else echo "would delete: $what"; fi
}

$YES || echo "DRY RUN - nothing is deleted. Re-run with --yes to delete."
[ -n "$APP" ] && step "app $APP" databricks apps delete "$APP"
step "serving endpoint wb-insights-agent" databricks serving-endpoints delete wb-insights-agent
for a in $ALERTS; do step "alert $a" databricks alerts-v2 trash-alert "$a"; done
[ -n "$GENIE" ] && step "Genie space $GENIE" databricks genie trash-space "$GENIE"
step "vector index wb_demo.gold.doc_chunks_index" databricks vector-search-indexes delete-index wb_demo.gold.doc_chunks_index
step "vector search endpoint wb_demo_vs" databricks vector-search-endpoints delete-endpoint wb_demo_vs
step "bundle resources (jobs, dashboards)" bash -c "cd '$ROOT' && databricks bundle destroy -t dev --auto-approve"
[ -n "$EXP_ID" ] && step "MLflow experiment $EXP_ID" databricks experiments delete-experiment "$EXP_ID"
step "catalog wb_demo (CASCADE)" databricks api post /api/2.0/sql/statements --json \
  "{\"warehouse_id\":\"$WH\",\"statement\":\"DROP CATALOG IF EXISTS wb_demo CASCADE\",\"wait_timeout\":\"50s\"}"
