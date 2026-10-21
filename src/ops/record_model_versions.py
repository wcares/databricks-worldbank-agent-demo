# Databricks notebook source
# MAGIC %md
# MAGIC # Record agent model versions in `ops.model_versions`
# MAGIC One row per registered version of `ml.wb_insights_agent`: its evaluation scores (stored as version tags
# MAGIC by `evaluate_and_register.py`), the LLM it used, and its aliases (`champion`, `challenger`). Feeds the
# MAGIC "Evaluation by model version" chart on the Agent operations dashboard.

# COMMAND ----------

# MAGIC %pip install -qqq mlflow[databricks]
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "wb_demo")
CATALOG = dbutils.widgets.get("catalog")
MODEL_NAME = f"{CATALOG}.ml.wb_insights_agent"

import mlflow
from mlflow import MlflowClient
from pyspark.sql import Row

mlflow.set_registry_uri("databricks-uc")
client = MlflowClient()
aliases = {}
for alias in ("champion", "challenger"):
    try:
        aliases.setdefault(client.get_model_version_by_alias(MODEL_NAME, alias).version, []).append(alias)
    except Exception:
        pass


def score(tags, key):
    try:
        return float(tags[key])
    except (KeyError, ValueError):
        return None


rows = []
for found in client.search_model_versions(f"name = '{MODEL_NAME}'"):
    # Search results do not carry usable tags (seen: "tags" was a function); fetch each version in full.
    mv = client.get_model_version(MODEL_NAME, found.version)
    tags = mv.tags if isinstance(mv.tags, dict) else {}
    rows.append(Row(
        version=int(mv.version), created_ms=int(mv.creation_timestamp), llm_endpoint=tags.get("llm_endpoint"),
        aliases=",".join(sorted(aliases.get(mv.version, []))),
        correctness=score(tags, "correctness_mean"), relevance=score(tags, "relevance_to_query_mean"),
        safety=score(tags, "safety_mean"), cites_source=score(tags, "cites_source_mean"),
        declines_off_topic=score(tags, "declines_off_topic_mean")))

schema = ("version INT, created_ms BIGINT, llm_endpoint STRING, aliases STRING, correctness DOUBLE, "
          "relevance DOUBLE, safety DOUBLE, cites_source DOUBLE, declines_off_topic DOUBLE")
df = spark.createDataFrame(rows, schema)
df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.ops.model_versions")
spark.sql(f"COMMENT ON TABLE {CATALOG}.ops.model_versions IS 'Registered versions of {MODEL_NAME} with evaluation scores and aliases'")
display(df.orderBy("version"))
assert rows, f"no versions found for {MODEL_NAME}"
