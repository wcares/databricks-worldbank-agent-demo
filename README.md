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
src/ops/            logging helpers, audit views
docs/               design notes and phase check results
```

## Status

Phase 0 (workspace check and foundation) — see `docs/phase0-checks.md`.

## Data and licence

World Bank data is used under CC BY 4.0. Code is MIT-licensed.
