# Databricks notebook source
# MAGIC %md
# MAGIC # Clean WDI data (silver)
# MAGIC Parses the latest bronze load into typed tables:
# MAGIC `silver.indicator_values` (MERGE upsert, one row per country / indicator / year),
# MAGIC `silver.countries` and `silver.indicators` (small dimensions, replaced each run).

# COMMAND ----------

dbutils.widgets.text("catalog", "wb_demo")
CATALOG = dbutils.widgets.get("catalog")

from pyspark.sql import functions as F

VALUE_SCHEMA = (
    "indicator struct<id:string,value:string>, country struct<id:string,value:string>, "
    "countryiso3code string, date string, value double, unit string, obs_status string, decimal int"
)
COUNTRY_SCHEMA = (
    "id string, iso2Code string, name string, region struct<id:string,value:string>, "
    "incomeLevel struct<id:string,value:string>, lendingType struct<id:string,value:string>, "
    "capitalCity string, longitude string, latitude string"
)
INDICATOR_SCHEMA = (
    "id string, name string, unit string, source struct<id:string,value:string>, sourceNote string, "
    "sourceOrganization string, topics array<struct<id:string,value:string>>"
)


def latest(table):
    df = spark.table(f"{CATALOG}.bronze.{table}")
    ts = df.agg(F.max("ingested_at")).first()[0]
    if ts is None:
        raise RuntimeError(f"{CATALOG}.bronze.{table} is empty; run ingest_wdi first.")
    return df.where(F.col("ingested_at") == ts)

# COMMAND ----------

values = (
    latest("wdi_raw")
    .select(F.from_json("payload", VALUE_SCHEMA).alias("r"), "ingest_run_id")
    .select(
        F.col("r.countryiso3code").alias("country_iso3"),
        F.col("r.indicator.id").alias("indicator_id"),
        F.col("r.date").cast("int").alias("year"),
        F.col("r.value").alias("value"),
        "ingest_run_id",
    )
    .where(F.col("value").isNotNull())
    .dropDuplicates(["country_iso3", "indicator_id", "year"])
)

spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CATALOG}.silver.indicator_values (
  country_iso3 STRING COMMENT 'ISO 3166-1 alpha-3 country code',
  indicator_id STRING COMMENT 'World Bank indicator code, e.g. EG.ELC.ACCS.ZS',
  year INT COMMENT 'Calendar year of the observation',
  value DOUBLE COMMENT 'Observed value, in the unit of the indicator',
  ingest_run_id STRING COMMENT 'Bronze load that last wrote this row',
  updated_at TIMESTAMP COMMENT 'When this row was last written'
) COMMENT 'World Development Indicators values, one row per country, indicator and year (non-null only)'
""")

values.createOrReplaceTempView("incoming_values")
merge = spark.sql(f"""
MERGE INTO {CATALOG}.silver.indicator_values t
USING incoming_values s
ON t.country_iso3 = s.country_iso3 AND t.indicator_id = s.indicator_id AND t.year = s.year
WHEN MATCHED AND (t.value <> s.value) THEN UPDATE SET t.value = s.value, t.ingest_run_id = s.ingest_run_id, t.updated_at = current_timestamp()
WHEN NOT MATCHED THEN INSERT (country_iso3, indicator_id, year, value, ingest_run_id, updated_at)
  VALUES (s.country_iso3, s.indicator_id, s.year, s.value, s.ingest_run_id, current_timestamp())
""")
display(merge)

# COMMAND ----------

countries = (
    latest("wdi_countries_raw")
    .select(F.from_json("payload", COUNTRY_SCHEMA).alias("c"))
    .select(
        F.col("c.id").alias("country_iso3"),
        F.col("c.iso2Code").alias("country_iso2"),
        F.trim("c.name").alias("country_name"),
        F.trim("c.region.value").alias("region"),
        F.trim("c.incomeLevel.value").alias("income_level"),
        F.trim("c.lendingType.value").alias("lending_type"),
        F.col("c.capitalCity").alias("capital_city"),
        F.col("c.latitude").cast("double").alias("latitude"),
        F.col("c.longitude").cast("double").alias("longitude"),
    )
)
countries.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.silver.countries")
spark.sql(f"COMMENT ON TABLE {CATALOG}.silver.countries IS 'Demo countries with World Bank region and income level'")

indicators = (
    latest("wdi_indicators_raw")
    .select(F.from_json("payload", INDICATOR_SCHEMA).alias("i"))
    .select(
        F.col("i.id").alias("indicator_id"),
        F.trim("i.name").alias("indicator_name"),
        F.col("i.sourceNote").alias("definition"),
        F.col("i.sourceOrganization").alias("source_organization"),
        F.concat_ws(", ", F.transform("i.topics", lambda t: F.trim(t["value"]))).alias("topics"),
    )
)
indicators.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.silver.indicators")
spark.sql(f"COMMENT ON TABLE {CATALOG}.silver.indicators IS 'Definitions and sources of the demo indicators'")

# COMMAND ----------

# Data quality: fail the task rather than pass on bad data.
checks = spark.sql(f"""
SELECT
  (SELECT count(*) FROM {CATALOG}.silver.indicator_values) AS value_rows,
  (SELECT count(*) FROM (SELECT country_iso3, indicator_id, year FROM {CATALOG}.silver.indicator_values
                         GROUP BY ALL HAVING count(*) > 1)) AS duplicate_keys,
  (SELECT count(*) FROM {CATALOG}.silver.countries) AS countries,
  (SELECT count(*) FROM {CATALOG}.silver.indicators) AS indicators
""").first()
print(checks.asDict())
assert checks.value_rows > 0, "silver.indicator_values is empty"
assert checks.duplicate_keys == 0, "duplicate country/indicator/year keys in silver.indicator_values"
assert checks.countries > 0 and checks.indicators > 0, "a dimension table is empty"
