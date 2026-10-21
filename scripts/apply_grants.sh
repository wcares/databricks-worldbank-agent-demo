#!/usr/bin/env bash
# Applies sql/10_grants.sql statement by statement on the SQL warehouse, then prints the resulting grants.
# Run by the workspace owner: it changes who can access what. Safe to re-run (GRANT is idempotent).
# Usage: scripts/apply_grants.sh [warehouse_id]
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WH=${1:-33fd48ef78c8fbfa}
run() {
  databricks api post /api/2.0/sql/statements --json "$(python3 -c 'import json,sys;print(json.dumps({"warehouse_id":sys.argv[1],"statement":sys.argv[2],"wait_timeout":"50s"}))' "$WH" "$1")" \
    | python3 -c 'import sys,json;d=json.load(sys.stdin);s=d["status"];print(s["state"], s.get("error",{}).get("message","")[:200]);[print("   ", r) for r in d.get("result",{}).get("data_array",[]) or []]'
}
# One statement per line: drop -- comments, split on ';', collapse whitespace.
python3 -c 'import sys,re;t="\n".join(l for l in open(sys.argv[1]) if not l.strip().startswith("--"));[print(re.sub(r"\s+"," ",x).strip()) for x in t.split(";") if x.strip()]' "$ROOT/sql/10_grants.sql" |
while IFS= read -r stmt; do
  [ -z "$stmt" ] && continue
  printf '%s\n  -> ' "$stmt" | cut -c1-120; run "$stmt"
done
for obj in "CATALOG wb_demo" "SCHEMA wb_demo.gold" "SCHEMA wb_demo.ops"; do echo "== grants on $obj"; run "SHOW GRANTS ON $obj"; done
