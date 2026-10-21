#!/usr/bin/env bash
# Applies the GRANT statements in sql/10_grants.sql through the Unity Catalog permissions API
# (databricks grants update), then prints the resulting grants. No SQL warehouse is needed: the first
# version ran the SQL on the warehouse and failed while the warehouse was stopped.
# Run by the workspace owner: it changes who can access what. Safe to re-run (adding a grant twice is a no-op).
# Usage: scripts/apply_grants.sh
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
python3 - "$ROOT/sql/10_grants.sql" <<'EOF'
import json, re, subprocess, sys

sql = "\n".join(l for l in open(sys.argv[1]) if not l.strip().startswith("--"))
pattern = re.compile(r"GRANT\s+(.+?)\s+ON\s+(CATALOG|SCHEMA|VOLUME|TABLE)\s+(\S+)\s+TO\s+(.+)", re.I | re.S)
targets = []
for stmt in (s.strip() for s in sql.split(";") if s.strip()):
    m = pattern.fullmatch(re.sub(r"\s+", " ", stmt))
    if not m:
        sys.exit(f"cannot parse: {stmt}")
    privileges = [p.strip().upper().replace(" ", "_") for p in m.group(1).split(",")]
    principals = [p.strip().strip("`") for p in m.group(4).split(",")]
    securable, name = m.group(2).lower(), m.group(3)
    changes = [{"principal": p, "add": privileges} for p in principals]
    out = subprocess.run(["databricks", "grants", "update", securable, name, "--json", json.dumps({"changes": changes}),
                         "-o", "json"], capture_output=True, text=True)
    status = "ok" if out.returncode == 0 else f"FAILED: {out.stderr.strip()[:200]}"
    print(f"{securable} {name}: {', '.join(privileges)} -> {', '.join(principals)}  [{status}]")
    if out.returncode != 0:
        sys.exit(1)
    targets.append((securable, name))

for securable, name in dict.fromkeys(targets):
    got = json.loads(subprocess.run(["databricks", "grants", "get", securable, name, "-o", "json"],
                                    capture_output=True, text=True, check=True).stdout)
    print(f"== {securable} {name}")
    for a in got.get("privilege_assignments", []):
        print(f"   {a['principal']}: {', '.join(sorted(a.get('privileges', [])))}")
EOF
