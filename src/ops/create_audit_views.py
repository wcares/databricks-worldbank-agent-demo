# Databricks notebook source
# MAGIC %md
# MAGIC # Audit and lineage views (`ops`)
# MAGIC Views over the Unity Catalog system tables, scoped to the demo catalog:
# MAGIC - `ops.v_audit_wb_demo`: every audited action that touched `wb_demo`, last 30 days.
# MAGIC - `ops.v_audit_denied`: the same, only failed or denied requests (status 4xx/5xx).
# MAGIC - `ops.v_table_lineage`: which job or pipeline wrote which `wb_demo` table, from what.
# MAGIC
# MAGIC Free Edition exposes `system.access` (audit, lineage) but not the billing or job-run system tables;
# MAGIC job history is kept in `ops.job_runs` instead (see `record_job_runs.py`).

# COMMAND ----------

dbutils.widgets.text("catalog", "wb_demo")
CATALOG = dbutils.widgets.get("catalog")

spark.sql(f"""
CREATE OR REPLACE VIEW {CATALOG}.ops.v_audit_wb_demo
COMMENT 'Audited actions on {CATALOG} objects in the last 30 days (system.access.audit)'
AS SELECT
  event_time,
  coalesce(user_identity.email, 'unknown') AS actor,
  service_name,
  action_name,
  response.status_code AS status_code,
  response.error_message AS error_message,
  request_params
FROM system.access.audit
WHERE event_date >= current_date() - INTERVAL 30 DAYS
  AND to_json(request_params) LIKE '%{CATALOG}%'
""")

spark.sql(f"""
CREATE OR REPLACE VIEW {CATALOG}.ops.v_audit_denied
COMMENT 'Failed or denied requests on {CATALOG} objects (status 4xx/5xx)'
AS SELECT * FROM {CATALOG}.ops.v_audit_wb_demo WHERE status_code >= 400
""")

spark.sql(f"""
CREATE OR REPLACE VIEW {CATALOG}.ops.v_table_lineage
COMMENT 'Table-level lineage into {CATALOG} tables (system.access.table_lineage)'
AS SELECT
  event_time,
  source_table_full_name,
  target_table_full_name,
  entity_type,
  entity_id,
  created_by
FROM system.access.table_lineage
WHERE target_table_full_name LIKE '{CATALOG}.%' OR source_table_full_name LIKE '{CATALOG}.%'
""")

# COMMAND ----------

display(spark.sql(f"SELECT status_code, count(*) AS n FROM {CATALOG}.ops.v_audit_wb_demo GROUP BY 1 ORDER BY 1"))
n = spark.sql(f"SELECT count(*) AS n FROM {CATALOG}.ops.v_audit_wb_demo").first().n
assert n > 0, "no audit events for the demo catalog; audit logs arrive with a delay on new workspaces"
