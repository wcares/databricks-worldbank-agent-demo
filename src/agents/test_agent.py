# Databricks notebook source
# MAGIC %md
# MAGIC # Test the multi-agent system
# MAGIC Runs the five demo questions through `agent.AGENT` and prints, for each one, which agents
# MAGIC were called and the final answer. MLflow tracing is on, so every run is in the experiment.
# MAGIC
# MAGIC Library versions are pinned together (PyPI, 2026-10-20): langgraph 1.2.x needs langgraph-prebuilt 1.1.x,
# MAGIC and langchain 1.4.6 needs langgraph >= 1.2.12. Unpinned installs mixed versions and failed to import.

# COMMAND ----------

# MAGIC %pip install -qqq langgraph==1.2.16 langgraph-prebuilt==1.1.1 langchain==1.4.6 langgraph-supervisor==0.0.31 databricks-langchain==0.21.0 databricks-agents==1.12.0 mlflow[databricks]
# MAGIC %restart_python

# COMMAND ----------

from importlib.metadata import version

print({p: version(p) for p in ['langgraph', 'langgraph-prebuilt', 'langgraph-supervisor', 'langchain', 'langchain-core',
                               'databricks-langchain', 'mlflow', 'databricks-agents']})

# COMMAND ----------

import re
import time

from agent import AGENT

QUESTIONS = [
    "What was Kenya's access to electricity in 2010 and in the latest year?",
    "What does the World Bank identify as the main constraints on growth in Bangladesh?",
    "Compare CO2 emissions per capita for India and Indonesia since 2000, and explain what World Bank reports say about their energy transition.",
    "Which three countries in the data reduced extreme poverty the most since 2000, and why?",
    "What is the weather in Paris today?",
]

results = []
for q in QUESTIONS:
    response = AGENT.predict({"input": [{"role": "user", "content": q}]})
    items = [i if isinstance(i, dict) else i.model_dump() for i in response.output]
    print(f"Q: {q}\n{len(items)} output items:")
    for it in items:
        kind = it.get("type")
        if kind == "message":
            text = " ".join(c.get("text", "") for c in (it.get("content") or []) if isinstance(c, dict))
            print(f"  [message] {text[:400]!r}")
        elif kind == "function_call":
            print(f"  [function_call] {it.get('name')} {str(it.get('arguments'))[:200]}")
        elif kind == "function_call_output":
            print(f"  [function_call_output] {str(it.get('output'))[:200]!r}")
        else:
            print(f"  [{kind}]")
    print("-" * 80)
    time.sleep(20)  # stay under the Free Edition model QPS limit between questions
