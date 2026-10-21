"""Generates development_data.lvdash.json, the "Development data" AI/BI dashboard.

Widget specs follow the shapes used in databricks/bundle-examples
(knowledge_base/dashboard_nyc_taxi and the SDP monitoring template).
Run: python3 src/dashboards/build_development_dashboard.py
"""
import json
import pathlib

T = "wb_demo.gold.country_indicator_wide"
DATASETS = [
    {"name": "wide", "displayName": "Indicators by country and year", "query": (
        "SELECT country_name, region, income_level, year, make_date(year, 1, 1) AS year_date,\n"
        "  electricity_access_pct, gdp_per_capita_usd, co2_per_capita_t, life_expectancy_years,\n"
        "  under5_mortality_per_1000, internet_users_pct, poverty_3usd_day_pct\n"
        f"FROM {T}")},
    {"name": "latest", "displayName": "Latest values by country", "query": (
        "SELECT country_name, region, income_level,\n"
        "  max_by(gdp_per_capita_usd, IF(gdp_per_capita_usd IS NULL, NULL, year)) AS gdp_per_capita_usd,\n"
        "  max_by(electricity_access_pct, IF(electricity_access_pct IS NULL, NULL, year)) AS electricity_access_pct,\n"
        "  max_by(life_expectancy_years, IF(life_expectancy_years IS NULL, NULL, year)) AS life_expectancy_years,\n"
        "  max(year) AS latest_year\n"
        f"FROM {T} GROUP BY ALL")},
]


def field(name, expr=None):
    return {"name": name, "expression": expr or f"`{name}`"}


def filter_widget(wid, column, title, pos):
    queries, fields = [], []
    for ds in ("wide", "latest"):
        qn = f"filter_{ds}_{column}"
        queries.append({"name": qn, "query": {"datasetName": ds, "disaggregated": False, "fields": [
            field(column), field(f"{column}_associativity", "COUNT_IF(`associative_filter_predicate_group`)")]}})
        fields.append({"fieldName": column, "displayName": title, "queryName": qn})
    return {"position": pos, "widget": {"name": wid, "queries": queries, "spec": {
        "version": 2, "widgetType": "filter-multi-select", "encodings": {"fields": fields},
        "frame": {"showTitle": True, "title": title}}}}


def counter(wid, ds, name, expr, title, pos):
    return {"position": pos, "widget": {"name": wid,
        "queries": [{"name": "main_query", "query": {"datasetName": ds, "disaggregated": False, "fields": [field(name, expr)]}}],
        "spec": {"version": 2, "widgetType": "counter", "encodings": {"value": {"fieldName": name, "displayName": title}},
                 "frame": {"showTitle": True, "title": title}}}}


def line(wid, column, title, y_title, pos):
    y = f"avg({column})"
    return {"position": pos, "widget": {"name": wid,
        "queries": [{"name": "main_query", "query": {"datasetName": "wide", "disaggregated": False, "fields": [
            field("year_date"), field(y, f"AVG(`{column}`)"), field("country_name")]}}],
        "spec": {"version": 3, "widgetType": "line", "encodings": {
            "x": {"fieldName": "year_date", "scale": {"type": "temporal"}, "displayName": "Year"},
            "y": {"fieldName": y, "scale": {"type": "quantitative"}, "displayName": y_title, "axis": {"title": y_title}},
            "color": {"fieldName": "country_name", "scale": {"type": "categorical"}, "displayName": "Country"}},
            "frame": {"showTitle": True, "title": title}}}}


def bar(wid, column, title, y_title, pos):
    y = f"sum({column})"
    return {"position": pos, "widget": {"name": wid,
        "queries": [{"name": "main_query", "query": {"datasetName": "latest", "disaggregated": False, "fields": [
            field("country_name"), field(y, f"SUM(`{column}`)")]}}],
        "spec": {"version": 3, "widgetType": "bar", "encodings": {
            "x": {"fieldName": "country_name", "scale": {"type": "categorical"}, "displayName": "Country"},
            "y": {"fieldName": y, "scale": {"type": "quantitative"}, "displayName": y_title, "axis": {"title": y_title}}},
            "frame": {"showTitle": True, "title": title}}}}


TEXT_COLUMNS = ("country_name", "region", "income_level")


def table_column(i, column, title):
    """Full column spec, as the dashboard editor writes it (see databricks/bundle-examples)."""
    text = column in TEXT_COLUMNS
    spec = {
        "fieldName": column, "displayName": title, "title": title, "order": 100000 + i, "visible": True,
        "type": "string" if text else ("integer" if column == "latest_year" else "float"),
        "displayAs": "string" if text else "number", "alignContent": "left" if text else "right",
        "allowHTML": False, "allowSearch": text, "booleanValues": ["false", "true"], "highlightLinks": False,
        "imageHeight": "", "imageTitleTemplate": "{{ @ }}", "imageUrlTemplate": "{{ @ }}", "imageWidth": "",
        "linkOpenInNewTab": True, "linkTextTemplate": "{{ @ }}", "linkTitleTemplate": "{{ @ }}",
        "linkUrlTemplate": "{{ @ }}", "preserveWhitespace": False, "useMonospaceFont": False,
    }
    if not text:
        spec["numberFormat"] = "0" if column == "latest_year" else "#,##0.0"
    return spec


def table(wid, columns, title, pos):
    return {"position": pos, "widget": {"name": wid,
        "queries": [{"name": "main_query", "query": {"datasetName": "latest", "disaggregated": True,
                                                     "fields": [field(c) for c, _ in columns]}}],
        "spec": {"version": 1, "widgetType": "table",
                 "encodings": {"columns": [table_column(i, c, t) for i, (c, t) in enumerate(columns)]},
                 "invisibleColumns": [], "allowHTMLByDefault": False, "itemsPerPage": 25,
                 "paginationSize": "default", "condensed": True, "withRowNumber": False,
                 "frame": {"showTitle": True, "title": title}}}}


def pos(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


layout = [
    {"position": pos(0, 0, 6, 2), "widget": {"name": "title", "textbox_spec":
        "# World Bank development data\nWorld Development Indicators for 20 countries, 2000 onward. "
        "Source: World Bank (CC BY 4.0), loaded by the `wb_demo_pipeline` job into `wb_demo.gold`."}},
    filter_widget("f_country", "country_name", "Country", pos(0, 2, 3, 1)),
    filter_widget("f_region", "region", "Region", pos(3, 2, 3, 1)),
    counter("k_countries", "latest", "countries", "COUNT(DISTINCT `country_name`)", "Countries", pos(0, 3, 2, 2)),
    counter("k_year", "latest", "latest_year", "MAX(`latest_year`)", "Most recent year in the data", pos(2, 3, 2, 2)),
    counter("k_elec", "latest", "avg_elec", "AVG(`electricity_access_pct`)", "Average electricity access, latest (%)", pos(4, 3, 2, 2)),
    line("l_elec", "electricity_access_pct", "Access to electricity", "% of population", pos(0, 5, 3, 6)),
    line("l_co2", "co2_per_capita_t", "CO2 emissions per capita", "t CO2e per person", pos(3, 5, 3, 6)),
    line("l_life", "life_expectancy_years", "Life expectancy at birth", "Years", pos(0, 11, 3, 6)),
    line("l_u5", "under5_mortality_per_1000", "Under-5 mortality", "Per 1,000 live births", pos(3, 11, 3, 6)),
    bar("b_gdp", "gdp_per_capita_usd", "GDP per capita, latest year", "Current US$", pos(0, 17, 6, 6)),
    table("t_latest", [("country_name", "Country"), ("region", "Region"), ("income_level", "Income group"),
                       ("gdp_per_capita_usd", "GDP per capita (US$)"), ("electricity_access_pct", "Electricity access (%)"),
                       ("life_expectancy_years", "Life expectancy (years)")],
          "Latest available value per country (the year can differ by indicator)", pos(0, 23, 6, 7)),
]

dashboard = {"datasets": DATASETS, "pages": [{"name": "overview", "displayName": "Overview", "layout": layout}]}
out = pathlib.Path(__file__).with_name("development_data.lvdash.json")
out.write_text(json.dumps(dashboard, indent=2) + "\n")
print(f"wrote {out}")
