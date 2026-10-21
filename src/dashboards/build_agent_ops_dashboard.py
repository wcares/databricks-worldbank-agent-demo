"""Generates agent_operations.lvdash.json, the "Agent operations" AI/BI dashboard.

Reads the wb_demo.ops tables filled by the wb_ops job: agent_requests (MLflow traces), job_runs (Jobs API),
model_versions (UC model versions + eval scores) and the audit views over system.access.audit.
Widget shapes follow databricks/bundle-examples, as in build_development_dashboard.py.
Run: python3 src/dashboards/build_agent_ops_dashboard.py
"""
import json
import pathlib

OPS = "wb_demo.ops"
DATASETS = [
    {"name": "requests", "displayName": "Agent requests", "query": (
        "SELECT source, state, date_format(timestamp_millis(request_time), 'yyyy-MM-dd HH:mm') AS requested_at,\n"
        "  round(latency_ms / 1000.0, 1) AS latency_s, coalesce(correctness, '') AS correctness, question\n"
        f"FROM {OPS}.agent_requests")},
    {"name": "versions", "displayName": "Agent model versions", "query": (
        "SELECT version, concat('v', version, IF(aliases = '', '', concat(' (', aliases, ')'))) AS version_label,\n"
        "  correctness, relevance, safety, cites_source, declines_off_topic, llm_endpoint, aliases\n"
        f"FROM {OPS}.model_versions")},
    {"name": "champion", "displayName": "Champion model version", "query": (
        f"SELECT version, correctness FROM {OPS}.model_versions WHERE aliases LIKE '%champion%'")},
    {"name": "jobs", "displayName": "Job runs", "query": (
        "SELECT regexp_replace(job_name, '^\\\\[dev [^]]*\\\\] ', '') AS job,\n"
        "  date_format(start_time, 'yyyy-MM-dd HH:mm') AS started_at, duration_s, coalesce(result_state, life_cycle_state) AS result,\n"
        f"  failed_tasks FROM {OPS}.job_runs")},
    {"name": "audit_daily", "displayName": "Audit events per day", "query": (
        "SELECT date_format(event_time, 'yyyy-MM-dd') AS day,\n"
        "  IF(status_code >= 400, 'failed or denied', 'succeeded') AS outcome, count(*) AS events\n"
        f"FROM {OPS}.v_audit_wb_demo GROUP BY ALL")},
    {"name": "denied", "displayName": "Failed or denied requests", "query": (
        "SELECT date_format(event_time, 'yyyy-MM-dd HH:mm:ss') AS event_time, actor, service_name, action_name,\n"
        f"  status_code, left(error_message, 160) AS error_message FROM {OPS}.v_audit_denied")},
]


def field(name, expr=None):
    return {"name": name, "expression": expr or f"`{name}`"}


def pos(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def counter(wid, ds, name, expr, title, p):
    return {"position": p, "widget": {"name": wid,
        "queries": [{"name": "main_query", "query": {"datasetName": ds, "disaggregated": False, "fields": [field(name, expr)]}}],
        "spec": {"version": 2, "widgetType": "counter", "encodings": {"value": {"fieldName": name, "displayName": title}},
                 "frame": {"showTitle": True, "title": title}}}}


def bar(wid, ds, x, y_name, y_expr, title, x_title, y_title, p, color=None):
    fields = [field(x), field(y_name, y_expr)] + ([field(color)] if color else [])
    enc = {"x": {"fieldName": x, "scale": {"type": "categorical"}, "displayName": x_title},
           "y": {"fieldName": y_name, "scale": {"type": "quantitative"}, "displayName": y_title, "axis": {"title": y_title}}}
    if color:
        enc["color"] = {"fieldName": color, "scale": {"type": "categorical"}, "displayName": color.replace("_", " ").title()}
    return {"position": p, "widget": {"name": wid,
        "queries": [{"name": "main_query", "query": {"datasetName": ds, "disaggregated": False, "fields": fields}}],
        "spec": {"version": 3, "widgetType": "bar", "encodings": enc, "frame": {"showTitle": True, "title": title}}}}


NUMBER_TYPES = {"latency_s": "float", "duration_s": "integer", "status_code": "integer", "version": "integer",
                "correctness": "float", "relevance": "float", "safety": "float", "cites_source": "float"}


def table_column(i, column, title):
    """Full column spec, as the dashboard editor writes it (see databricks/bundle-examples)."""
    kind = NUMBER_TYPES.get(column, "string")
    text = kind == "string"
    spec = {
        "fieldName": column, "displayName": title, "title": title, "order": 100000 + i, "visible": True,
        "type": kind, "displayAs": "string" if text else "number", "alignContent": "left" if text else "right",
        "allowHTML": False, "allowSearch": text, "booleanValues": ["false", "true"], "highlightLinks": False,
        "imageHeight": "", "imageTitleTemplate": "{{ @ }}", "imageUrlTemplate": "{{ @ }}", "imageWidth": "",
        "linkOpenInNewTab": True, "linkTextTemplate": "{{ @ }}", "linkTitleTemplate": "{{ @ }}",
        "linkUrlTemplate": "{{ @ }}", "preserveWhitespace": False, "useMonospaceFont": False,
    }
    if not text:
        spec["numberFormat"] = "0" if kind == "integer" else "0.00"
    return spec


def table(wid, ds, columns, title, p):
    return {"position": p, "widget": {"name": wid,
        "queries": [{"name": "main_query", "query": {"datasetName": ds, "disaggregated": True,
                                                     "fields": [field(c) for c, _ in columns]}}],
        "spec": {"version": 1, "widgetType": "table",
                 "encodings": {"columns": [table_column(i, c, t) for i, (c, t) in enumerate(columns)]},
                 "invisibleColumns": [], "allowHTMLByDefault": False, "itemsPerPage": 25,
                 "paginationSize": "default", "condensed": True, "withRowNumber": False,
                 "frame": {"showTitle": True, "title": title}}}}


layout = [
    {"position": pos(0, 0, 6, 2), "widget": {"name": "title", "textbox_spec":
        "# Agent operations\nRequests, latency and quality of the World Bank agent, pipeline job health, and audit "
        "events on `wb_demo`. Refreshed by the `wb_ops` job from MLflow traces, the Jobs API, the model registry and "
        "`system.access.audit`."}},
    counter("k_requests", "requests", "requests", "COUNT(`question`)", "Agent requests (all)", pos(0, 2, 2, 2)),
    counter("k_latency", "requests", "avg_latency", "AVG(`latency_s`)", "Average latency (s)", pos(2, 2, 2, 2)),
    # A counter rejected a conditional MAX(IF(...)) expression ("Select fields to visualize"); it reads its own dataset.
    counter("k_champion", "champion", "champion_correctness", "MAX(`correctness`)",
            "Champion correctness (eval)", pos(4, 2, 2, 2)),
    bar("b_versions", "versions", "version_label", "correctness", "MAX(`correctness`)",
        "Evaluation correctness by model version", "Model version", "Correctness (0-1)", pos(0, 4, 3, 6)),
    bar("b_sources", "requests", "source", "request_count", "COUNT(`question`)",
        "Requests by source", "Source", "Requests", pos(3, 4, 3, 6)),
    table("t_jobs", "jobs", [("job", "Job"), ("started_at", "Started (UTC)"), ("duration_s", "Duration (s)"),
                             ("result", "Result"), ("failed_tasks", "Failed tasks")],
          "Pipeline and agent job runs", pos(0, 10, 6, 7)),
    bar("b_audit", "audit_daily", "day", "events", "SUM(`events`)", "Audit events on wb_demo per day",
        "Day", "Events", pos(0, 17, 6, 6), color="outcome"),
    table("t_denied", "denied", [("event_time", "Time (UTC)"), ("actor", "Actor"), ("service_name", "Service"),
                                 ("action_name", "Action"), ("status_code", "Status"), ("error_message", "Error")],
          "Failed or denied requests (audit log)", pos(0, 23, 6, 7)),
    table("t_requests", "requests", [("requested_at", "Requested (UTC)"), ("source", "Source"),
                                     ("latency_s", "Latency (s)"), ("correctness", "Judge"), ("question", "Question")],
          "Recent agent requests", pos(0, 30, 6, 8)),
]

dashboard = {"datasets": DATASETS, "pages": [{"name": "operations", "displayName": "Operations", "layout": layout}]}
out = pathlib.Path(__file__).with_name("agent_operations.lvdash.json")
out.write_text(json.dumps(dashboard, indent=2) + "\n")
print(f"wrote {out}")
