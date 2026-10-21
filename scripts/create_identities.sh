#!/usr/bin/env bash
# Creates the demo's groups and the agent's service principal in the workspace.
# Run it yourself after reviewing it: it changes who can do what in the workspace.
# Idempotent: an identity that already exists is reported and skipped.
# Requires: databricks CLI logged in as a workspace admin (databricks auth login).
set -u

exists_group() { databricks groups list -o json | grep -q "\"displayName\": *\"$1\""; }
exists_sp() { databricks service-principals list -o json | grep -q "\"displayName\": *\"$1\""; }

for g in wb_engineers wb_analysts wb_auditors; do
  if exists_group "$g"; then echo "group $g: already exists"
  else databricks groups create --display-name "$g" >/dev/null && echo "group $g: created" || echo "group $g: FAILED"
  fi
done

if exists_sp wb_agent_sp; then echo "service principal wb_agent_sp: already exists"
else databricks service-principals create --display-name wb_agent_sp >/dev/null && echo "service principal wb_agent_sp: created" || echo "service principal wb_agent_sp: FAILED"
fi

echo "--- now present:"
databricks groups list -o json | grep -o '"displayName": *"wb_[^"]*"'
databricks service-principals list -o json | grep -o '"displayName": *"wb_[^"]*"'
