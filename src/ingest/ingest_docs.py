# Databricks notebook source
# MAGIC %md
# MAGIC # Ingest World Bank reports (bronze)
# MAGIC Finds analytical reports for the demo countries with the Documents & Reports API v3,
# MAGIC downloads new PDFs into the volume `bronze.raw_docs`, and appends their metadata to
# MAGIC `bronze.docs_raw`. Files already in the volume are not downloaded again.

# COMMAND ----------

dbutils.widgets.text("catalog", "wb_demo")
dbutils.widgets.text("max_docs", "40")
dbutils.widgets.text("max_mb", "40")
dbutils.widgets.text("per_country", "2")
CATALOG = dbutils.widgets.get("catalog")
MAX_DOCS = int(dbutils.widgets.get("max_docs"))
MAX_BYTES = int(dbutils.widgets.get("max_mb")) * 1024 * 1024
PER_COUNTRY = int(dbutils.widgets.get("per_country"))
VOLUME = f"/Volumes/{CATALOG}/bronze/raw_docs"

# ISO3 -> country name as the Documents API spells it (checked 2026-10-20).
COUNTRIES = {
    "KEN": "Kenya", "NGA": "Nigeria", "ETH": "Ethiopia", "GHA": "Ghana", "ZAF": "South Africa",
    "EGY": "Egypt, Arab Republic of", "MAR": "Morocco", "IND": "India", "BGD": "Bangladesh",
    "PAK": "Pakistan", "IDN": "Indonesia", "VNM": "Viet Nam", "PHL": "Philippines", "CHN": "China",
    "BRA": "Brazil", "MEX": "Mexico", "COL": "Colombia", "PER": "Peru", "TUR": "Turkiye",
    "USA": "United States",
}
# Analytical report types; project paperwork (resettlement plans, safeguards) is left out.
DOC_TYPES = [
    "Country Economic Memorandum",
    "Poverty Assessment",
    "Country Climate and Development Report",
    "Systematic Country Diagnostic",
]

# COMMAND ----------

import datetime
import os
import time
import uuid

import requests

API = "https://search.worldbank.org/api/v3/wds"
HEADERS = {"User-Agent": "Mozilla/5.0 (wb-demo ingest; Databricks)"}
RUN_ID = str(uuid.uuid4())
INGESTED_AT = datetime.datetime.now(datetime.timezone.utc)
FIELDS = "display_title,docty,count,docdt,lang,pdfurl,url,abstracts,repnb"


def get(url, **kw):
    for attempt in range(4):
        try:
            r = requests.get(url, headers=HEADERS, timeout=kw.pop("timeout", 120), **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)


def candidates(country, doc_type):
    """Newest English reports of one type for one country, one per distinct title."""
    params = {"format": "json", "docty_exact": doc_type, "count_exact": country, "rows": 20, "fl": FIELDS}
    docs = get(API, params=params).json().get("documents", {})
    rows = [dict(v, doc_id=k) for k, v in docs.items() if k != "facets" and v.get("pdfurl") and v.get("lang") == "English"]
    rows.sort(key=lambda r: r.get("docdt", ""), reverse=True)
    seen, out = set(), []
    for r in rows:
        key = (r.get("display_title") or "")[:60].lower()
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out

# COMMAND ----------

os.makedirs(VOLUME, exist_ok=True)
picked, skipped = [], []
for iso3, name in COUNTRIES.items():
    for doc_type in DOC_TYPES:
        taken = sum(p["country_iso3"] == iso3 for p in picked)
        if len(picked) >= MAX_DOCS or taken >= PER_COUNTRY:
            break
        for doc in candidates(name, doc_type):
            path = f"{VOLUME}/{doc['doc_id']}.pdf"
            if not os.path.exists(path):
                url = doc["pdfurl"].replace("http://", "https://", 1)
                try:
                    body = get(url, timeout=300).content
                except requests.RequestException as e:
                    skipped.append((doc["doc_id"], f"download failed: {e}"))
                    continue  # try the next candidate of this type
                if not body.startswith(b"%PDF") or len(body) > MAX_BYTES:
                    skipped.append((doc["doc_id"], f"not a PDF or too large ({len(body)} bytes)"))
                    continue
                with open(path, "wb") as f:
                    f.write(body)
            picked.append({
                "doc_id": doc["doc_id"], "country_iso3": iso3, "doc_type": doc_type,
                "title": doc.get("display_title"), "doc_date": (doc.get("docdt") or "")[:10],
                "report_number": doc.get("repnb"), "pdf_url": doc["pdfurl"], "landing_url": doc.get("url"),
                "abstract": (doc.get("abstracts") or {}).get("cdata!") if isinstance(doc.get("abstracts"), dict) else doc.get("abstracts"),
                "file_path": path, "file_bytes": os.path.getsize(path),
            })
            break  # one report per country and type
print(f"picked {len(picked)} documents, skipped {len(skipped)}")
for s in skipped:
    print("skipped", s)

# COMMAND ----------

from pyspark.sql import Row

if not picked:
    raise RuntimeError("No documents were downloaded; refusing to report success.")
rows = [Row(**p, ingest_run_id=RUN_ID, ingested_at=INGESTED_AT) for p in picked]
df = spark.createDataFrame(rows)
df.write.mode("append").option("mergeSchema", "true").saveAsTable(f"{CATALOG}.bronze.docs_raw")
display(df.groupBy("doc_type").count())
