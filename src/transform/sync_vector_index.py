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

# Wait (up to 60 min) until the index has caught up with the source table: state ONLINE_NO_PENDING_UPDATE
# (the state observed on a fully synced index, 2026-10-20) AND as many indexed rows as source rows.
source_rows = spark.table(spec["delta_sync_index_spec"]["source_table"]).count()
time.sleep(60)  # give a just-triggered sync time to start before the first check
deadline = time.time() + 3600
while True:
    s = status()
    state, rows = s.get("detailed_state"), s.get("indexed_row_count")
    print(f"{state} indexed={rows} source={source_rows}")
    if s.get("ready") and state == "ONLINE_NO_PENDING_UPDATE" and rows == source_rows:
        break
    if time.time() > deadline:
        raise TimeoutError(f"{name} not caught up after 60 minutes: {s}")
    time.sleep(60)
