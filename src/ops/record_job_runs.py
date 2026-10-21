# Databricks notebook source
# MAGIC %md
# MAGIC # Record job runs in `ops.job_runs`
# MAGIC Free Edition has no job-run system tables (`system.lakeflow`), so this task copies the recent runs of
# MAGIC every demo job (name contains `wb_`) from the Jobs API into a Delta table: one row per run with its
# MAGIC duration, result and the tasks that failed. The Agent operations dashboard and the job-failure alert
# MAGIC read this table.

# COMMAND ----------

dbutils.widgets.text("catalog", "wb_demo")
CATALOG = dbutils.widgets.get("catalog")

from datetime import datetime, timezone

from databricks.sdk import WorkspaceClient
from pyspark.sql import Row

w = WorkspaceClient()


def ts(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if ms else None


rows = []
for job in w.jobs.list():
    name = job.settings.name if job.settings else ""
    if "wb_" not in name:
        continue
    for run in w.jobs.list_runs(job_id=job.job_id, expand_tasks=True, limit=25):
        state = run.state
        tasks = run.tasks or []
        rows.append(Row(
            run_id=run.run_id,
            job_name=name,
            start_time=ts(run.start_time),
            end_time=ts(run.end_time) if run.end_time else None,
            duration_s=round((run.end_time - run.start_time) / 1000) if run.end_time and run.start_time else None,
            life_cycle_state=str(state.life_cycle_state.value) if state and state.life_cycle_state else None,
            result_state=str(state.result_state.value) if state and state.result_state else None,
            tasks_run=len([t for t in tasks if t.state and t.state.result_state]),
            failed_tasks=",".join(sorted({t.task_key for t in tasks if t.state and t.state.result_state
                                          and t.state.result_state.value not in ("SUCCESS", "EXCLUDED")})),
            run_page_url=run.run_page_url,
        ))
print(f"{len(rows)} runs")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.ops.job_runs (
  run_id BIGINT COMMENT 'Jobs API run id',
  job_name STRING COMMENT 'Job name (dev deployments carry a [dev user] prefix)',
  start_time TIMESTAMP, end_time TIMESTAMP,
  duration_s BIGINT COMMENT 'Run duration in seconds',
  life_cycle_state STRING, result_state STRING COMMENT 'SUCCESS, FAILED, ...',
  tasks_run INT COMMENT 'Tasks that reached a result in this run',
  failed_tasks STRING COMMENT 'Comma-separated task keys that did not succeed',
  run_page_url STRING
) COMMENT 'Recent runs of the demo jobs, from the Jobs API'
""")
if rows:
    spark.createDataFrame(rows).createOrReplaceTempView("incoming_runs")
    spark.sql(f"""
    MERGE INTO {CATALOG}.ops.job_runs t USING incoming_runs s ON t.run_id = s.run_id
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """)
display(spark.sql(f"""SELECT job_name, result_state, count(*) AS runs FROM {CATALOG}.ops.job_runs
                      GROUP BY ALL ORDER BY job_name, result_state"""))
