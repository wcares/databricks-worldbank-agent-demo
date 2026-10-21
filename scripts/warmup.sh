#!/usr/bin/env bash
# Run 15-20 minutes before presenting. On Free Edition the agent endpoint scales to zero and the SQL warehouse
# stops when idle, so the first request of the demo would otherwise wait for both to start.
#  1. starts the SQL warehouse (dashboards, Genie, alerts)
#  2. sends one question to the agent endpoint and waits for the answer (wakes the endpoint)
#  3. refreshes the ops tables (audit views, request log, job runs, model versions)
# Usage: scripts/warmup.sh [warehouse_id]
set -euo pipefail
WH=${1:-33fd48ef78c8fbfa}
ENDPOINT=wb-insights-agent
ROOT=$(cd "$(dirname "$0")/.." && pwd)

echo "1/3 starting SQL warehouse $WH"
databricks warehouses start "$WH" >/dev/null 2>&1 || true   # already running is fine
databricks api post /api/2.0/sql/statements --json "{\"warehouse_id\":\"$WH\",\"statement\":\"SELECT 1\",\"wait_timeout\":\"50s\"}" \
  | python3 -c 'import sys,json;print("   warehouse:", json.load(sys.stdin)["status"]["state"])'

echo "2/3 waking endpoint $ENDPOINT (a cold start can take several minutes)"
start=$(date +%s)
# While the endpoint scales up from zero it answers with an error instead of JSON (seen on the first try),
# so keep asking for up to ~15 minutes.
for attempt in $(seq 1 30); do
  reply=$(databricks api post "/serving-endpoints/$ENDPOINT/invocations" \
    --json '{"input":[{"role":"user","content":"What was Kenya'"'"'s access to electricity in 2022?"}]}' 2>&1 || true)
  answer=$(printf '%s' "$reply" | python3 -c '
import sys,json
try:
    d=json.load(sys.stdin)
except ValueError:
    sys.exit(1)
texts=[c.get("text","") for i in d.get("output",[]) if i.get("type")=="message" for c in i.get("content",[])]
texts=[t for t in texts if not t.startswith("<name>")]
print(texts[-1] if texts else "")' 2>/dev/null) && [ -n "$answer" ] && break
  echo "   attempt $attempt: not ready yet ($(printf '%s' "$reply" | head -c 120 | tr '\n' ' '))"
  sleep 30
done
[ -n "${answer:-}" ] || { echo "   endpoint did not answer"; exit 1; }
echo "   answer: $answer"
echo "   endpoint answered after $(( $(date +%s) - start )) s"

echo "3/3 refreshing ops tables (wb_ops job)"
cd "$ROOT" && databricks bundle run wb_ops -t dev 2>&1 | grep -E "TERMINATED|FAILED" | tail -1
echo "ready"
