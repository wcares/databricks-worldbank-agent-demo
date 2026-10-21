# Databricks notebook source
# MAGIC %md
# MAGIC # Ingest World Development Indicators (bronze)
# MAGIC Pulls the demo's indicators for the demo's countries from the World Bank Indicators API v2
# MAGIC and appends them, untouched, to `bronze.wdi_raw`. Country and indicator metadata land in
# MAGIC `bronze.wdi_countries_raw` and `bronze.wdi_indicators_raw`. Every row carries the run id.

# COMMAND ----------

dbutils.widgets.text("catalog", "wb_demo")
dbutils.widgets.text("start_year", "2000")
CATALOG = dbutils.widgets.get("catalog")
START_YEAR = int(dbutils.widgets.get("start_year"))

# ISO3 codes: a spread of regions and income levels.
COUNTRIES = [
    "KEN", "NGA", "ETH", "GHA", "ZAF", "EGY", "MAR",   # Africa
    "IND", "BGD", "PAK",                               # South Asia
    "IDN", "VNM", "PHL", "CHN",                        # East Asia & Pacific
    "BRA", "MEX", "COL", "PER",                        # Latin America
    "TUR", "USA",                                      # Europe & Central Asia, North America
]

# Codes checked against api.worldbank.org/v2/indicator on 2026-10-20.
# EN.ATM.CO2E.PC is archived; EN.GHG.CO2.PC.CE.AR5 replaces it.
INDICATORS = [
    "NY.GDP.PCAP.CD",        # GDP per capita (current US$)
    "NY.GDP.MKTP.KD.ZG",     # GDP growth (annual %)
    "SI.POV.DDAY",           # Poverty headcount ratio at $3.00 a day (2021 PPP)
    "EG.ELC.ACCS.ZS",        # Access to electricity (% of population)
    "EN.GHG.CO2.PC.CE.AR5",  # CO2 emissions excl. LULUCF per capita (t CO2e/capita)
    "SP.DYN.LE00.IN",        # Life expectancy at birth (years)
    "SE.PRM.ENRR",           # School enrollment, primary (% gross)
    "SP.POP.TOTL",           # Population, total
    "SH.DYN.MORT",           # Under-5 mortality (per 1,000 live births)
    "EG.FEC.RNEW.ZS",        # Renewable energy consumption (% of final energy)
    "SL.UEM.TOTL.ZS",        # Unemployment (% of labor force, ILO modeled)
    "NE.EXP.GNFS.ZS",        # Exports of goods and services (% of GDP)
    "SH.XPD.CHEX.GD.ZS",     # Current health expenditure (% of GDP)
    "IT.NET.USER.ZS",        # Individuals using the Internet (%)
    "FP.CPI.TOTL.ZG",        # Inflation, consumer prices (annual %)
]

# COMMAND ----------

import datetime
import json
import time
import uuid

import requests

BASE = "https://api.worldbank.org/v2"
RUN_ID = str(uuid.uuid4())
INGESTED_AT = datetime.datetime.now(datetime.timezone.utc)


def fetch_all(path, params=None):
    """Return every row of a paged World Bank API v2 response; raise on an API error message."""
    params = {"format": "json", "per_page": 1000, **(params or {})}
    rows, page = [], 1
    while True:
        for attempt in range(4):
            try:
                resp = requests.get(f"{BASE}/{path}", params={**params, "page": page}, timeout=60)
                resp.raise_for_status()
                body = resp.json()
                break
            except (requests.RequestException, ValueError):
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)
        if len(body) < 2:
            raise RuntimeError(f"World Bank API error for {path}: {body}")
        meta, data = body[0], body[1] or []
        rows.extend(data)
        if page >= int(meta["pages"]):
            return rows
        page += 1

# COMMAND ----------

country_path = "country/" + ";".join(COUNTRIES)
values = []
for code in INDICATORS:
    rows = fetch_all(f"{country_path}/indicator/{code}", {"date": f"{START_YEAR}:{INGESTED_AT.year}"})
    print(f"{code}: {len(rows)} rows")
    values.extend(rows)

countries = fetch_all(country_path)
indicators = [fetch_all(f"indicator/{code}")[0] for code in INDICATORS]

# COMMAND ----------

from pyspark.sql import Row


def to_rows(items, key_fn):
    return [Row(record_key=key_fn(i), payload=json.dumps(i), ingest_run_id=RUN_ID, ingested_at=INGESTED_AT) for i in items]


def append(items, key_fn, table):
    df = spark.createDataFrame(to_rows(items, key_fn))
    df.write.mode("append").option("mergeSchema", "true").saveAsTable(f"{CATALOG}.bronze.{table}")
    print(f"appended {df.count()} rows to {CATALOG}.bronze.{table}")


append(values, lambda r: f"{r['countryiso3code']}|{r['indicator']['id']}|{r['date']}", "wdi_raw")
append(countries, lambda r: r["id"], "wdi_countries_raw")
append(indicators, lambda r: r["id"], "wdi_indicators_raw")

if not values:
    raise RuntimeError("No indicator rows were returned; refusing to report success.")
dbutils.jobs.taskValues.set("ingest_run_id", RUN_ID)
