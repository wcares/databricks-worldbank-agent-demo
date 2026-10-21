# Databricks notebook source
# MAGIC %md
# MAGIC # Export agent traces to `ops.agent_requests`
# MAGIC Free Edition does not support inference tables on agent endpoints ("Inference table is not currently
# MAGIC supported for this endpoint type in this workspace"), so the request log comes from MLflow traces:
# MAGIC every call to the agent (evaluation runs and the serving endpoint) is traced. This task copies one
# MAGIC row per trace into a Delta table so the request log can be queried, dashboarded and alerted on.

# COMMAND ----------

# MAGIC %pip install -qqq mlflow[databricks]
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "wb_demo")
CATALOG = dbutils.widgets.get("catalog")

import json

import mlflow

user = spark.sql("SELECT current_user()").first()[0]
# Agent experiment, plus the deploy notebook's experiment, where the first endpoint version sent its traces.
names = [f"/Users/{user}/wb_insights_agent", f"/Users/{user}/.bundle/wb_demo/dev/files/src/agents/deploy_agent"]
experiments = {e.experiment_id: e.name for n in names if (e := mlflow.get_experiment_by_name(n))}
print(experiments)


def _load(value):
    """Trace request/response: a dict, a JSON string, or plain text (evaluation predict_fn uses plain text)."""
    if isinstance(value, dict) or value is None:
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def question_of(request):
    req = _load(request)
    if isinstance(req, str):
        return req
    try:
        if "question" in req:  # evaluation calls predict_fn(question, group)
            return req["question"]
        msgs = req.get("input") or req.get("request", {}).get("input") or []
        users = [m.get("content") for m in msgs if isinstance(m, dict) and m.get("role") == "user"]
        return users[-1] if users else None
    except Exception:
        return None


def answer_of(response):
    resp = _load(response)
    if isinstance(resp, str):
        return resp  # evaluation predict_fn returns the answer text
    try:
        texts = [c.get("text", "") for it in resp.get("output", []) if it.get("type") == "message"
                 for c in it.get("content", []) if isinstance(c, dict)]
        texts = [t for t in texts if not t.startswith("<name>")]
        return texts[-1] if texts else None
    except Exception:
        return None


def correctness_of(assessments):
    for a in assessments or []:
        if a.get("assessment_name") == "correctness":
            return str((a.get("feedback") or {}).get("value"))
    return None

# COMMAND ----------

from pyspark.sql import Row

rows = []
for exp_id, exp_name in experiments.items():
    # include_spans must stay True: request and response are read from the root span (None without spans).
    df = mlflow.search_traces(locations=[exp_id], include_spans=True)
    for t in df.to_dict("records"):
        meta = t.get("trace_metadata") or {}
        rows.append(Row(
            trace_id=t["trace_id"],
            experiment=exp_name.split("/")[-1],
            source="evaluation" if "mlflow.sourceRun" in meta else "serving",
            request_time=int(t["request_time"]) if t.get("request_time") is not None else None,
            latency_ms=int(t["execution_duration"]) if t.get("execution_duration") is not None else None,
            state=str(t.get("state")),
            question=question_of(t.get("request")),
            answer=answer_of(t.get("response")),
            correctness=correctness_of(t.get("assessments")),
        ))
print(f"{len(rows)} traces")

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.ops.agent_requests (
  trace_id STRING COMMENT 'MLflow trace id',
  experiment STRING COMMENT 'MLflow experiment the trace was logged to',
  source STRING COMMENT 'evaluation (MLflow evaluate run) or serving (model serving endpoint)',
  request_time BIGINT COMMENT 'Request start, epoch milliseconds',
  latency_ms BIGINT COMMENT 'End-to-end agent latency in milliseconds',
  state STRING COMMENT 'Trace state (OK / ERROR)',
  question STRING COMMENT 'User question',
  answer STRING COMMENT 'Final answer text',
  correctness STRING COMMENT 'Correctness judge verdict, evaluation traces only'
) COMMENT 'One row per agent request, copied from MLflow traces'
""")
if rows:
    # Explicit schema: a column that is empty in every row (e.g. correctness on serving traces) cannot be inferred.
    schema = ("trace_id STRING, experiment STRING, source STRING, request_time BIGINT, latency_ms BIGINT, "
              "state STRING, question STRING, answer STRING, correctness STRING")
    spark.createDataFrame(rows, schema).createOrReplaceTempView("incoming_traces")
    spark.sql(f"""
    MERGE INTO {CATALOG}.ops.agent_requests t USING incoming_traces s ON t.trace_id = s.trace_id
    WHEN MATCHED THEN UPDATE SET *
    WHEN NOT MATCHED THEN INSERT *
    """)
display(spark.sql(f"""SELECT source, state, count(*) AS requests, round(avg(latency_ms) / 1000, 1) AS avg_latency_s
                      FROM {CATALOG}.ops.agent_requests GROUP BY ALL"""))
