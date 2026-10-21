"""Creates (or updates) the demo's Databricks SQL alerts (alerts v2) on the wb_demo.ops tables.

Alerts are created PAUSED: on Free Edition each scheduled evaluation starts the SQL warehouse and uses the
free compute allowance. Unpause one in the UI, or evaluate it on demand, during the demo.
Field names follow the sql.AlertV2Evaluation / sql.CronSchedule definitions in `databricks bundle schema`.
Usage: python3 scripts/create_alerts.py <warehouse_id>
"""
import json
import subprocess
import sys

WAREHOUSE_ID = sys.argv[1]
OPS = "wb_demo.ops"
SCHEDULE = {"quartz_cron_schedule": "0 15 * * * ?", "timezone_id": "UTC", "pause_status": "PAUSED"}

ALERTS = [
    {"display_name": "wb_demo: pipeline job failed in the last 24 hours",
     "query_text": (f"SELECT count(*) AS failed_runs FROM {OPS}.job_runs "
                    "WHERE result_state = 'FAILED' AND start_time >= current_timestamp() - INTERVAL 24 HOURS"),
     "evaluation": {"source": {"name": "failed_runs"}, "comparison_operator": "GREATER_THAN",
                    "threshold": {"value": {"double_value": 0}}}},
    {"display_name": "wb_demo: champion agent correctness below 0.8",
     "query_text": f"SELECT max(correctness) AS champion_correctness FROM {OPS}.model_versions WHERE aliases LIKE '%champion%'",
     "evaluation": {"source": {"name": "champion_correctness"}, "comparison_operator": "LESS_THAN",
                    "threshold": {"value": {"double_value": 0.8}}}},
    {"display_name": "wb_demo: agent p95 latency above 60 s",
     "query_text": (f"SELECT coalesce(percentile(latency_ms, 0.95) / 1000, 0) AS p95_latency_s FROM {OPS}.agent_requests "
                    "WHERE source = 'serving' AND request_time >= unix_millis(current_timestamp() - INTERVAL 24 HOURS)"),
     "evaluation": {"source": {"name": "p95_latency_s"}, "comparison_operator": "GREATER_THAN",
                    "threshold": {"value": {"double_value": 60}}}},
]


def cli(*args):
    out = subprocess.run(["databricks", *args, "-o", "json"], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip())
    return json.loads(out.stdout) if out.stdout.strip() else {}


existing = cli("alerts-v2", "list-alerts")
existing = existing if isinstance(existing, list) else existing.get("alerts", [])
by_name = {a["display_name"]: a["id"] for a in existing}

for alert in ALERTS:
    body = {**alert, "warehouse_id": WAREHOUSE_ID, "schedule": SCHEDULE}
    if alert["display_name"] in by_name:
        alert_id = by_name[alert["display_name"]]
        cli("alerts-v2", "update-alert", alert_id, "display_name,query_text,warehouse_id,evaluation,schedule",
            "--json", json.dumps(body))
        print(f"updated  {alert['display_name']} ({alert_id})")
    else:
        created = cli("alerts-v2", "create-alert", "--json", json.dumps(body))
        print(f"created  {alert['display_name']} ({created.get('id')})")
