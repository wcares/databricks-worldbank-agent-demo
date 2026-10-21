# Databricks notebook source
# MAGIC %md
# MAGIC # Log, evaluate, register and promote the agent
# MAGIC 1. Log `src/agents/agent.py` as an MLflow model (models-from-code) with the resources it calls.
# MAGIC 2. Evaluate it on `ml.eval_questions` with MLflow GenAI judges plus a custom "cites a source" check.
# MAGIC 3. Register it in Unity Catalog as `ml.wb_insights_agent`, alias `challenger`.
# MAGIC 4. Promotion gate: move alias `champion` to this version only if its correctness is at least the champion's.
# MAGIC
# MAGIC Library versions are pinned together (see `src/agents/test_agent.py`).

# COMMAND ----------

# MAGIC %pip install -qqq langgraph==1.2.16 langgraph-prebuilt==1.1.1 langchain==1.4.6 databricks-langchain==0.21.0 databricks-agents==1.12.0 mlflow[databricks]
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "wb_demo")
dbutils.widgets.text("warehouse_id", "33fd48ef78c8fbfa")
CATALOG = dbutils.widgets.get("catalog")
WAREHOUSE_ID = dbutils.widgets.get("warehouse_id")
MODEL_NAME = f"{CATALOG}.ml.wb_insights_agent"

import json
import os
import sys
from importlib.metadata import version

# Free Edition model endpoints have a low rate limit: one question at a time, two judges at a time.
os.environ["MLFLOW_GENAI_EVAL_MAX_WORKERS"] = "1"
os.environ["MLFLOW_GENAI_EVAL_MAX_SCORER_WORKERS"] = "2"

AGENT_DIR = os.path.abspath("../agents")
sys.path.append(AGENT_DIR)

import mlflow

user = spark.sql("SELECT current_user()").first()[0]
mlflow.set_experiment(f"/Users/{user}/wb_insights_agent")

# COMMAND ----------

import agent as agent_module
from agent import AGENT, GENIE_SPACE_ID, LLM_ENDPOINT_NAME, report_search
from mlflow.models.resources import (DatabricksGenieSpace, DatabricksServingEndpoint, DatabricksSQLWarehouse,
                                     DatabricksTable)

resources = [
    DatabricksServingEndpoint(endpoint_name=LLM_ENDPOINT_NAME),
    DatabricksGenieSpace(genie_space_id=GENIE_SPACE_ID),
    DatabricksSQLWarehouse(warehouse_id=WAREHOUSE_ID),
    *[DatabricksTable(table_name=f"{CATALOG}.{t}") for t in
      ("gold.country_indicator_wide", "gold.indicator_facts", "silver.indicators")],
    *report_search.resources,  # the Vector Search index and its embedding endpoint
]
pip_requirements = [f"{p}=={version(p)}" for p in
                    ("mlflow", "langgraph", "langgraph-prebuilt", "langchain", "langchain-core", "databricks-langchain")]
print(pip_requirements)

input_example = {"input": [{"role": "user", "content": "What was Kenya's access to electricity in 2022?"}]}

# COMMAND ----------


def final_text(response) -> str:
    """The last message that is not a <name>step</name> marker."""
    items = [i if isinstance(i, dict) else i.model_dump() for i in response.output]
    texts = [c.get("text", "") for it in items if it.get("type") == "message"
             for c in (it.get("content") or []) if isinstance(c, dict)]
    texts = [t for t in texts if not t.startswith("<name>")]
    return texts[-1] if texts else ""


def predict_fn(question: str, group: str) -> str:
    return final_text(AGENT.predict({"input": [{"role": "user", "content": question}]}))


from mlflow.genai.scorers import Correctness, Guidelines, RelevanceToQuery, Safety, scorer


@scorer
def cites_source(inputs, outputs) -> bool:
    """Every on-topic answer must name its source: World Bank WDI data or a World Bank report/link."""
    if inputs.get("group") == "off_topic":
        return True
    text = (outputs or "").lower()
    return "world bank wdi" in text or "documents.worldbank.org" in text or "report" in text


scorers = [
    Correctness(),
    RelevanceToQuery(),
    Safety(),
    Guidelines(name="declines_off_topic", guidelines=(
        "If the question is not about country development, economics, poverty, energy, climate, health or education, "
        "the response must decline to answer. Otherwise this guideline is satisfied.")),
    cites_source,
]

questions = spark.table(f"{CATALOG}.ml.eval_questions").collect()
eval_data = [{"inputs": {"question": r.question, "group": r.group},
              "expectations": {"expected_facts": json.loads(r.expected_facts)}} for r in questions]
print(f"{len(eval_data)} evaluation questions")

# COMMAND ----------

with mlflow.start_run(run_name=f"wb_insights_agent ({LLM_ENDPOINT_NAME})") as run:
    logged = mlflow.pyfunc.log_model(
        name="agent",
        python_model=os.path.join(AGENT_DIR, "agent.py"),
        resources=resources,
        pip_requirements=pip_requirements,
        input_example=input_example,
    )
    mlflow.log_params({"llm_endpoint": LLM_ENDPOINT_NAME, "index": agent_module.INDEX_NAME,
                       "genie_space_id": GENIE_SPACE_ID, "eval_questions": len(eval_data)})
    results = mlflow.genai.evaluate(data=eval_data, predict_fn=predict_fn, scorers=scorers)

metrics = {k: v for k, v in results.metrics.items() if k.endswith("/mean")}
print(json.dumps(metrics, indent=2))

# COMMAND ----------

from mlflow import MlflowClient

mlflow.set_registry_uri("databricks-uc")
client = MlflowClient()
mv = mlflow.register_model(logged.model_uri, MODEL_NAME)
for k, v in metrics.items():
    client.set_model_version_tag(MODEL_NAME, mv.version, k.replace("/", "_"), f"{v:.4f}")
client.set_model_version_tag(MODEL_NAME, mv.version, "llm_endpoint", LLM_ENDPOINT_NAME)
client.set_registered_model_alias(MODEL_NAME, "challenger", mv.version)

score = metrics.get("correctness/mean", 0.0)
try:
    champion = client.get_model_version_by_alias(MODEL_NAME, "champion")
    champion_score = float(champion.tags.get("correctness_mean", "0"))
except Exception:  # no champion yet
    champion, champion_score = None, -1.0

if score >= champion_score:
    client.set_registered_model_alias(MODEL_NAME, "champion", mv.version)
    decision = f"PROMOTED version {mv.version} to champion (correctness {score:.2f} >= {champion_score:.2f})"
else:
    decision = f"KEPT champion version {champion.version} (challenger {score:.2f} < {champion_score:.2f})"
print(decision)
dbutils.jobs.taskValues.set("decision", decision)
dbutils.jobs.taskValues.set("model_version", str(mv.version))
