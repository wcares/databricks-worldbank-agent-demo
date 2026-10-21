# Databricks × World Bank multi-agent demo

A demo-ready multi-agent system on Databricks that answers questions about countries' development
using World Bank **structured** data (World Development Indicators) and **unstructured** data
(World Bank reports, PDFs).

It shows, end to end: Workspace · Lakehouse · Delta Lake · Unity Catalog · Workflows ·
Databricks SQL · MLflow · Evaluation · Model Serving · audit logs · application/system logs.

## How it works

1. A Workflows job pulls WDI indicators and report PDFs into bronze Delta tables / a UC volume.
2. It cleans them into silver, builds gold tables, chunks and embeds reports into a Vector Search (AI Search) index.
3. A supervisor agent routes each question to a **data analyst** agent (Genie / SQL over gold) and a
   **document researcher** agent (retrieval over report chunks), then writes one cited answer.
4. The agent is logged with MLflow, evaluated, registered in Unity Catalog and served from a Model Serving endpoint.
5. Audit logs, lineage, traces, inference tables and app logs make every step inspectable.

## Layout

```
databricks.yml      Asset Bundle (deploy with: databricks bundle deploy -t dev)
resources/          Jobs, endpoints and other bundle resources
sql/                Unity Catalog setup and SQL objects
src/ingest/         WDI + Documents & Reports ingestion
src/transform/      silver / gold tables, parsing, chunking
src/agents/         supervisor + specialist agents
src/eval/           evaluation set and judges
src/ops/            audit views, request log, job runs, model versions
src/dashboards/     dashboard generators and .lvdash.json files
genie/              Genie space definition and tests
scripts/            warm-up, grants, alerts, chat app, teardown
docs/               design notes and phase check results
```

## Status

All phases built and verified on Databricks Free Edition (2026-10-21):
data pipeline, Genie space, report index, four-agent workflow, evaluation and promotion gate, serving endpoint,
chat app, ops tables, dashboards and alerts. Run the demo with `docs/demo-runbook.md`; check results in
`docs/phase0-checks.md`. Design and build journal: see the design doc linked from the runbook.

## Scripts

| Script | Does |
| --- | --- |
| `scripts/warmup.sh` | Wakes the warehouse and the scale-to-zero endpoint before a demo |
| `scripts/create_identities.sh` | Creates the demo groups and the agent service principal (owner runs it) |
| `scripts/apply_grants.sh` | Applies `sql/10_grants.sql` (owner runs it) |
| `scripts/create_alerts.py` | Creates or updates the 3 SQL alerts |
| `scripts/deploy_chat_app.sh` | Deploys the Databricks chat UI template against the endpoint |
| `scripts/teardown.sh` | Lists (or with `--yes` deletes) everything the demo created |

## Data and licence

World Bank data is used under CC BY 4.0. Code is MIT-licensed.
