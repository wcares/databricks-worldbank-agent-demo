#!/usr/bin/env bash
# Creates the "World Bank development data" Genie space from genie/wb_space.json.
# Usage: genie/create_space.sh <warehouse_id>
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
body=$(python3 -c 'import json,sys
space=open(sys.argv[1]).read()
print(json.dumps({"warehouse_id":sys.argv[2],"serialized_space":json.dumps(json.loads(space)),
  "title":"World Bank development data","description":"Ask about World Bank development indicators for 20 countries since 2000."}))' "$here/wb_space.json" "$1")
databricks api post /api/2.0/genie/spaces --json "$body"
