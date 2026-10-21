# Databricks notebook source
# MAGIC %md
# MAGIC # Sync the report Vector Search index (gold)
# MAGIC Creates `gold.doc_chunks_index` from `doc_chunks_index.json` if it does not exist yet,
# MAGIC otherwise triggers a sync so new or changed chunks in `silver.doc_chunks` are embedded.

# COMMAND ----------

import json
import time

from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
spec = json.load(open("doc_chunks_index.json"))
name = spec["name"]


def status():
    return w.api_client.do("GET", f"/api/2.0/vector-search/indexes/{name}")["status"]


try:
    status()
    w.api_client.do("POST", f"/api/2.0/vector-search/indexes/{name}/sync")
    print(f"sync triggered for {name}")
except Exception as e:  # the index does not exist yet
    if "RESOURCE_DOES_NOT_EXIST" not in str(e) and "does not exist" not in str(e).lower():
        raise
    w.api_client.do("POST", "/api/2.0/vector-search/indexes", body=spec)
    print(f"created {name}")

# COMMAND ----------

# Wait (up to 60 min) until the index is ready, so the evaluation task downstream sees fresh data.
deadline = time.time() + 3600
while True:
    s = status()
    print(s.get("detailed_state"), s.get("indexed_row_count"), s.get("message", "")[:120])
    if s.get("ready") and "SYNC" not in (s.get("detailed_state") or "").replace("ONLINE_NO_PENDING_UPDATE", ""):
        break
    if time.time() > deadline:
        raise TimeoutError(f"{name} not ready after 60 minutes: {s}")
    time.sleep(60)
