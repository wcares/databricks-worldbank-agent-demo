#!/usr/bin/env bash
# Replaces the contents of an existing Genie space with genie/wb_space.json.
# Usage: genie/update_space.sh <space_id>
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
body=$(python3 -c 'import json,sys;print(json.dumps({"serialized_space": json.dumps(json.load(open(sys.argv[1])))}))' "$here/wb_space.json")
databricks api patch "/api/2.0/genie/spaces/$1" --json "$body"
