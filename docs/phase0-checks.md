# Phase 0 checks — Databricks Free Edition (2026-10-20)

| Check | Result | How |
| --- | --- | --- |
| World Bank Indicators API reachable from serverless | OK — Kenya EG.ELC.ACCS.ZS 2022 = 76 | `urllib` call in a notebook |
| Documents & Reports API v3 reachable | OK — `qterm=kenya energy` total 2334 | `urllib` call in a notebook |
| Create catalog / schemas / volume | OK | `sql/00_setup_uc.sql` |
| `ai_parse_document` | Available — returns its result struct (tested on a fake 9-byte PDF only) | SQL editor |
| `system.access.audit` | Readable, 0 rows on a new account — re-check after activity | SQL editor |
| `system.access.table_lineage`, `column_lineage` | Present | Catalog Explorer |
| Billing / job-run system tables | Absent — job health comes from Workflows UI + `ops.job_runs` | Catalog Explorer |
| Models (Unity Gateway) | GPT OSS 120B, Qwen3 Next Instruct, Gemma 3 12B, GTE Large (En) | AI Gateway page |
| Menus present (not yet exercised) | Genie Agents, AI Search, Apps, Lakebase, Serving, Experiments | UI |

Open: account groups and service principal on Free Edition; Databricks CLI login on the dev machine.
