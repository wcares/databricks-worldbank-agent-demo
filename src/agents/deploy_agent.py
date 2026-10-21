# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy the champion agent to Model Serving
# MAGIC Deploys the model version that holds the `champion` alias of `ml.wb_insights_agent` with
# MAGIC `databricks.agents.deploy`, which creates (or updates) the serving endpoint, its inference
# MAGIC tables and the Review App. Then sends one question to the endpoint as a smoke test.

# COMMAND ----------

# MAGIC %pip install -qqq databricks-agents==1.12.0 mlflow[databricks]
# MAGIC %restart_python

# COMMAND ----------

dbutils.widgets.text("catalog", "wb_demo")
CATALOG = dbutils.widgets.get("catalog")
MODEL_NAME = f"{CATALOG}.ml.wb_insights_agent"

import mlflow
from databricks import agents
from mlflow import MlflowClient

mlflow.set_registry_uri("databricks-uc")
champion = MlflowClient().get_model_version_by_alias(MODEL_NAME, "champion")
print(f"deploying {MODEL_NAME} version {champion.version} (champion)")

# Free Edition requires scale-to-zero on every serving endpoint (deploy failed without it: "Scale to zero
# must be enabled for this workspace"). Consequence: the first request after idle is a cold start.
# Send production traces to the agent experiment, next to the evaluation runs. Without this, deploy
# uses this notebook's own experiment, which is deleted whenever the notebook is (seen 2026-10-21).
user = spark.sql("SELECT current_user()").first()[0]
experiment = mlflow.get_experiment_by_name(f"/Users/{user}/wb_insights_agent")
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
ENDPOINT = "wb-insights-agent"
env = {"MLFLOW_EXPERIMENT_ID": experiment.experiment_id}
try:
    deployment = agents.deploy(MODEL_NAME, int(champion.version), endpoint_name=ENDPOINT, scale_to_zero=True,
                               environment_vars=env, tags={"project": "wb_demo"}, deploy_feedback_model=False)
    print("review app:", getattr(deployment, "review_app_url", None))
except ValueError as e:
    # agents.deploy refuses to redeploy the version already served ("already serves model ... version N").
    # Keep that served version and update only its environment variables in place.
    if "already serves" not in str(e):
        raise
    cfg = w.api_client.do("GET", f"/api/2.0/serving-endpoints/{ENDPOINT}")["config"]
    keep = ("name", "entity_name", "entity_version", "workload_size", "scale_to_zero_enabled",
            "environment_vars", "workload_type")
    entities = [{k: s[k] for k in keep if k in s} for s in cfg["served_entities"]]
    for s in entities:
        s.setdefault("environment_vars", {}).update(env)
    body = {"served_entities": entities, **({"traffic_config": cfg["traffic_config"]} if cfg.get("traffic_config") else {})}
    w.api_client.do("PUT", f"/api/2.0/serving-endpoints/{ENDPOINT}/config", body=body)
    print(f"version {champion.version} already served; environment updated in place")
print("endpoint:", ENDPOINT)
dbutils.jobs.taskValues.set("endpoint_name", ENDPOINT)

# COMMAND ----------

# Wait for the endpoint to be ready, then ask one question through it.
import time

deadline = time.time() + 45 * 60
while True:
    ep = w.serving_endpoints.get(ENDPOINT)
    ready, config = str(ep.state.ready), str(ep.state.config_update)
    print(time.strftime("%H:%M:%S"), ready, config)
    if ready.endswith("READY") and not config.endswith("IN_PROGRESS"):
        break
    if config.endswith("UPDATE_FAILED") or time.time() > deadline:
        raise RuntimeError(f"endpoint not ready: {ready} {config}")
    time.sleep(60)

reply = w.api_client.do("POST", f"/serving-endpoints/{ENDPOINT}/invocations",
                        body={"input": [{"role": "user", "content": "What was Kenya's access to electricity in 2022?"}]})
texts = [c.get("text", "") for item in reply.get("output", []) if item.get("type") == "message"
         for c in item.get("content", [])]
answer = [t for t in texts if not t.startswith("<name>")][-1]
print("endpoint answer:", answer)
assert "76" in answer, "smoke test: expected Kenya 2022 electricity access (76.0%) in the answer"
