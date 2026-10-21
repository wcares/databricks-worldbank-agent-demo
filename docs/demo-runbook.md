# Demo runbook — World Bank multi-agent system on Databricks

About 25 minutes. Each step names the Databricks service it shows. Workspace:
https://dbc-3e5e3ff8-a3ea.cloud.databricks.com (Free Edition).

## Before the demo (20 minutes ahead)

0. Do not rebuild or re-evaluate on demo day: the Free Edition daily compute limit (see below) would stop the demo.
1. `scripts/warmup.sh` — starts the SQL warehouse, wakes the agent endpoint (it scales to zero on Free Edition;
   the first answer after idle can take minutes), refreshes the ops tables. Wait for `ready`.
2. Open these tabs:

| Tab | Link |
| --- | --- |
| Catalog `wb_demo` | https://dbc-3e5e3ff8-a3ea.cloud.databricks.com/explore/data/wb_demo?o=7474658798551782 |
| Job `wb_demo_pipeline` | https://dbc-3e5e3ff8-a3ea.cloud.databricks.com/jobs/299817836636879?o=7474658798551782 |
| Dashboard "World Bank development data" | https://dbc-3e5e3ff8-a3ea.cloud.databricks.com/dashboardsv3/01f1ccf1f3a61fa195b794bf5361f75b?o=7474658798551782 |
| Genie "World Bank development data" | https://dbc-3e5e3ff8-a3ea.cloud.databricks.com/genie/rooms/01f1ccf0ce021ae2bbdb20a34b5b1c25?o=7474658798551782 |
| Chat app | https://db-chatbot-dev-suryayadav3228-7474658798551782.aws.databricksapps.com |
| MLflow experiment `wb_insights_agent` | https://dbc-3e5e3ff8-a3ea.cloud.databricks.com/ml/experiments/3933110245844773?o=7474658798551782 |
| Model `wb_demo.ml.wb_insights_agent` | https://dbc-3e5e3ff8-a3ea.cloud.databricks.com/explore/data/models/wb_demo/ml/wb_insights_agent?o=7474658798551782 |
| Serving endpoint `wb-insights-agent` | https://dbc-3e5e3ff8-a3ea.cloud.databricks.com/ml/endpoints/wb-insights-agent?o=7474658798551782 |
| Dashboard "Agent operations" | https://dbc-3e5e3ff8-a3ea.cloud.databricks.com/dashboardsv3/01f1cd1529791541aa29ac68d9934319?o=7474658798551782 |
| Job `wb_agent_release` | https://dbc-3e5e3ff8-a3ea.cloud.databricks.com/jobs/633973990739306?o=7474658798551782 |

3. Fallback: have the screen recording of a full run ready (see the end).

## The walkthrough

| # | Show | Service | Say | ~Min |
| --- | --- | --- | --- | --- |
| 1 | Repo and `databricks.yml`; workspace files under `.bundle/wb_demo` | Workspace, Asset Bundles | "Everything is code in git and deploys with one command." | 1 |
| 2 | Job `wb_demo_pipeline`: task graph, last run; press Run now | Workflows | Two branches: indicators (API → bronze → silver → gold) and reports (PDF → parse → chunk → vector index). | 3 |
| 3 | Catalog: `bronze.wdi_raw` (raw JSON), volume `raw_docs` (PDFs), `silver.indicator_values`, `gold.country_indicator_wide`; History tab | Lakehouse, Delta Lake | MERGE upserts, time travel (`DESCRIBE HISTORY`), Change Data Feed on `silver.doc_chunks` feeds the index. | 3 |
| 4 | Lineage tab of `gold.country_indicator_wide`; tags `source`, `licence`; Permissions tab | Unity Catalog | Every asset — tables, volume, index, model, functions — lives in one governed catalog. | 2 |
| 5 | Dashboard "World Bank development data" | Databricks SQL | Kenya electricity access 19.2% (2010) → 77.0% (2024). | 2 |
| 6 | Chat app: ask the 5 questions below | Model Serving | One endpoint, four agents behind it. | 4 |
| 7 | MLflow experiment → Traces → the CO2 question | MLflow tracing | Router plan, Genie SQL, retrieved report passages, writer — each step with timing. | 3 |
| 8 | Experiment → Evaluation runs; model version tags; `champion` alias on v2 | Evaluation, MLflow, UC registry | 20 questions, LLM judges: correctness 0.80 → 0.90; the gate moved `champion` only because v2 scored higher. | 3 |
| 9 | SQL editor: revoke the agent service principal's read on gold, grant it back (below) | Unity Catalog | Access is enforced and every change is audited. | 2 |
| 10 | Dashboard "Agent operations": failed/denied requests, job runs | Audit logs, system logs | The revoke from step 9 and the failed runs from the build are in the log. | 1 |
| 11 | Alerts list: "pipeline job failed in the last 24 hours" | Databricks SQL alerts | Paused on Free Edition; evaluate on demand. | 1 |

### Questions for step 6 (all five verified through the serving endpoint on 2026-10-21, 14–34 s each)

1. What was Kenya's access to electricity in 2010 and in the latest year? — numbers only → data analyst (Genie).
2. What does the World Bank identify as the main constraints on growth in Bangladesh? — reports only → document researcher.
3. Compare CO2 emissions per capita for India and Indonesia since 2000, and explain what World Bank reports say about their energy transition. — both.
4. Which three countries in the data reduced extreme poverty the most since 2000, and why? — both: Indonesia, China,
   India. The indexed reports do not explain the "why", and the agent says so instead of inventing a reason.
5. What is the weather in Paris today? — refused.

### Step 9: revoke and audit (run as the workspace owner in the SQL editor)

The agent's service principal `wb_agent_sp` has read access to `wb_demo.gold` (`sql/10_grants.sql`). On Free
Edition grants go to the service principal: workspace-local groups cannot receive Unity Catalog grants.

```sql
SHOW GRANTS ON SCHEMA wb_demo.gold;                                    -- wb_agent_sp: USE SCHEMA, SELECT
REVOKE SELECT ON SCHEMA wb_demo.gold FROM `a8d69acf-15e5-44fa-9cf0-0406432dafb7`;
SHOW GRANTS ON SCHEMA wb_demo.gold;                                    -- SELECT gone
GRANT SELECT ON SCHEMA wb_demo.gold TO `a8d69acf-15e5-44fa-9cf0-0406432dafb7`;
-- a few minutes later (audit logs arrive with a delay):
SELECT event_time, actor, action_name, request_params
FROM wb_demo.ops.v_audit_wb_demo
WHERE action_name = 'updatePermissions' ORDER BY event_time DESC;  -- action name to be confirmed after the first grant
```

## Free Edition notes for the audience

- **Daily compute limit.** Free Edition stops all compute once a daily allowance is used ("you have hit your
  free daily limit. Please come back again tomorrow", hit on 2026-10-21 after a day of builds and evaluations).
  On demo day run only `scripts/warmup.sh` and the demo itself: no full pipeline runs, no evaluations, no
  redeploys. Rehearse on a different day from the demo.
- Serving endpoints must scale to zero, so the first request after idle is slow — hence the warm-up.
- No inference tables on agent endpoints: the request log is built from MLflow traces (`ops.agent_requests`).
- No job-run or billing system tables: job history comes from the Jobs API (`ops.job_runs`).
- Embedding runs at about 2 s per chunk, so each report keeps its first 80 chunks (2,784 in total).
- Model endpoints are rate limited; the agent retries with backoff.

## Recording the fallback

Record the walkthrough once with a screen recorder after a successful warm-up, so the demo can run from video if
the workspace is slow on the day.

## After the demo

`scripts/teardown.sh` lists everything the demo created; `scripts/teardown.sh --yes` deletes it.
