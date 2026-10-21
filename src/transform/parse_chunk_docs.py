# Databricks notebook source
# MAGIC %md
# MAGIC # Parse and chunk World Bank reports (silver)
# MAGIC 1. `ai_parse_document` turns each new PDF in `bronze.docs_raw` into structured elements
# MAGIC    (`silver.doc_parsed`, one row per document; already-parsed documents are skipped).
# MAGIC 2. Body elements are grouped into ~500-token chunks that keep the document title, the
# MAGIC    current section heading and the page range (`silver.doc_chunks`, Change Data Feed on,
# MAGIC    so the Vector Search index can sync from it).

# COMMAND ----------

dbutils.widgets.text("catalog", "wb_demo")
dbutils.widgets.text("chunk_chars", "2000")
dbutils.widgets.text("overlap_chars", "200")
CATALOG = dbutils.widgets.get("catalog")
CHUNK_CHARS = int(dbutils.widgets.get("chunk_chars"))
OVERLAP = int(dbutils.widgets.get("overlap_chars"))

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.silver.doc_parsed (
  doc_id STRING, file_path STRING, parsed STRING, parsed_at TIMESTAMP
) COMMENT 'ai_parse_document output (JSON string) for each report PDF'
""")

# Latest metadata row per document; parse only documents not parsed yet.
spark.sql(f"""
CREATE OR REPLACE TEMP VIEW docs_latest AS
SELECT * FROM {CATALOG}.bronze.docs_raw
QUALIFY row_number() OVER (PARTITION BY doc_id ORDER BY ingested_at DESC) = 1
""")
todo = [r.doc_id for r in spark.sql(f"""
SELECT d.doc_id FROM docs_latest d
LEFT ANTI JOIN {CATALOG}.silver.doc_parsed p ON p.doc_id = d.doc_id
""").collect()]
print(f"{len(todo)} documents to parse")

if todo:
    # read_files takes one path, not a list: read the volume folder and keep only the documents to parse.
    ids = ", ".join(f"'{d}'" for d in todo)
    spark.sql(f"""
    INSERT INTO {CATALOG}.silver.doc_parsed
    SELECT doc_id, regexp_replace(path, '^dbfs:', '') AS file_path,
           CAST(ai_parse_document(content) AS STRING) AS parsed, current_timestamp()
    FROM (SELECT *, regexp_extract(path, '([^/]+)[.]pdf$', 1) AS doc_id
          FROM read_files('/Volumes/{CATALOG}/bronze/raw_docs', format => 'binaryFile'))
    WHERE doc_id IN ({ids})
    """)

# COMMAND ----------

import json
import re

KEEP = {"title", "section_header", "text", "table", "caption", "footnote"}
TAG = re.compile(r"<[^>]+>")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def pieces(content):
    """Split text longer than one chunk at sentence ends, so no chunk is far over budget."""
    if len(content) <= CHUNK_CHARS:
        return [content]
    out, cur = [], ""
    for sentence in SENTENCE_END.split(content):
        if cur and len(cur) + len(sentence) > CHUNK_CHARS:
            out.append(cur)
            cur = ""
        cur = f"{cur} {sentence}".strip()
    return out + ([cur] if cur else [])


def chunks_for(doc_id, parsed_json):
    """Yield (n, section, page_start, page_end, text) chunks for one parsed document."""
    doc = json.loads(parsed_json).get("document") or {}
    section, buf, pages, n = "", [], [], 0

    def flush():
        nonlocal buf, pages, n
        body = "\n".join(buf).strip()
        if len(body) >= 200:  # drop fragments too short to answer anything
            yield n, section, min(pages), max(pages), body
            n += 1
        tail = body[-OVERLAP:] if OVERLAP else ""
        buf, pages = ([tail] if tail else []), (pages[-1:] if pages else [])

    for el in doc.get("elements", []):
        kind, content = el.get("type"), (el.get("content") or "").strip()
        if kind not in KEEP or not content:
            continue
        page = (el.get("bbox") or [{}])[0].get("page_id", 0) + 1
        if kind == "table":
            content = TAG.sub(" ", content)
            content = re.sub(r"\s+", " ", content)
        if kind == "section_header":
            if sum(len(b) for b in buf) > OVERLAP:
                yield from flush()
            section = content[:200]
        for piece in pieces(content):
            if buf and sum(len(b) for b in buf) + len(piece) > CHUNK_CHARS:
                yield from flush()
            buf.append(piece)
            pages.append(page)
    if buf:
        yield from flush()

# COMMAND ----------

from pyspark.sql import Row

meta = {r.doc_id: r for r in spark.table("docs_latest").collect()}
rows, errors = [], []
for p in spark.table(f"{CATALOG}.silver.doc_parsed").collect():
    m = meta.get(p.doc_id)
    if m is None:
        continue
    status = json.loads(p.parsed).get("error_status")
    if status:
        errors.append((p.doc_id, str(status)[:200]))
    year = int(m.doc_date[:4]) if m.doc_date else None
    for n, section, p0, p1, text in chunks_for(p.doc_id, p.parsed):
        header = f"{m.title} ({m.doc_type}, {m.doc_date[:4] if m.doc_date else 'n.d.'})" + (f" - {section}" if section else "")
        rows.append(Row(chunk_id=f"{p.doc_id}-{n:04d}", doc_id=p.doc_id, country_iso3=m.country_iso3,
                        doc_type=m.doc_type, title=m.title, doc_year=year, section=section,
                        page_start=p0, page_end=p1, landing_url=m.landing_url,
                        chunk_text=f"{header}\n\n{text}"))
print(f"{len(rows)} chunks from {len({r.doc_id for r in rows})} documents; {len(errors)} documents with parse errors")
for e in errors:
    print("parse error", e)

# COMMAND ----------

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.silver.doc_chunks (
  chunk_id STRING NOT NULL COMMENT 'Document id plus chunk number',
  doc_id STRING COMMENT 'World Bank Documents & Reports id',
  country_iso3 STRING COMMENT 'Country the report covers',
  doc_type STRING COMMENT 'Report type, e.g. Country Economic Memorandum',
  title STRING COMMENT 'Report title',
  doc_year INT COMMENT 'Year the report was published',
  section STRING COMMENT 'Nearest section heading above the chunk',
  page_start INT COMMENT 'First PDF page of the chunk',
  page_end INT COMMENT 'Last PDF page of the chunk',
  landing_url STRING COMMENT 'Report page on documents.worldbank.org',
  chunk_text STRING COMMENT 'Chunk text, prefixed with title, type, year and section'
) COMMENT 'Report chunks for retrieval; source of the Vector Search index'
TBLPROPERTIES (delta.enableChangeDataFeed = true)
""")

if not rows:
    raise RuntimeError("No chunks produced; refusing to report success.")
spark.createDataFrame(rows).createOrReplaceTempView("incoming_chunks")
# MERGE conditions cannot hold a subquery, so the re-chunked documents are listed literally.
doc_ids = ", ".join(sorted({f"'{r.doc_id}'" for r in rows}))
display(spark.sql(f"""
MERGE INTO {CATALOG}.silver.doc_chunks t USING incoming_chunks s ON t.chunk_id = s.chunk_id
WHEN MATCHED AND t.chunk_text <> s.chunk_text THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
WHEN NOT MATCHED BY SOURCE AND t.doc_id IN ({doc_ids}) THEN DELETE
"""))
