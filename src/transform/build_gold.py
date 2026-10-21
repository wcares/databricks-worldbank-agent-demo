# Databricks notebook source
# MAGIC %md
# MAGIC # Build gold tables for the data analyst agent
# MAGIC - `gold.indicator_facts`: long format, every value with country and indicator names.
# MAGIC - `gold.country_indicator_wide`: one row per country and year, one readable column per indicator.

# COMMAND ----------

dbutils.widgets.text("catalog", "wb_demo")
CATALOG = dbutils.widgets.get("catalog")

# Indicator code -> readable column name in the wide table.
COLUMNS = {
    "NY.GDP.PCAP.CD": "gdp_per_capita_usd",
    "NY.GDP.MKTP.KD.ZG": "gdp_growth_pct",
    "SI.POV.DDAY": "poverty_3usd_day_pct",
    "EG.ELC.ACCS.ZS": "electricity_access_pct",
    "EN.GHG.CO2.PC.CE.AR5": "co2_per_capita_t",
    "SP.DYN.LE00.IN": "life_expectancy_years",
    "SE.PRM.ENRR": "primary_enrollment_gross_pct",
    "SP.POP.TOTL": "population",
    "SH.DYN.MORT": "under5_mortality_per_1000",
    "EG.FEC.RNEW.ZS": "renewable_energy_pct",
    "SL.UEM.TOTL.ZS": "unemployment_pct",
    "NE.EXP.GNFS.ZS": "exports_pct_gdp",
    "SH.XPD.CHEX.GD.ZS": "health_expenditure_pct_gdp",
    "IT.NET.USER.ZS": "internet_users_pct",
    "FP.CPI.TOTL.ZG": "inflation_pct",
}
TAGS = "('source' = 'World Bank WDI', 'licence' = 'CC BY 4.0')"


def sql_str(s):
    return (s or "").replace("'", "''")

# COMMAND ----------

spark.sql(f"""
CREATE OR REPLACE TABLE {CATALOG}.gold.indicator_facts
COMMENT 'World Development Indicators in long format: one row per country, indicator and year, with names'
AS SELECT
  c.country_iso3, c.country_name, c.region, c.income_level,
  v.indicator_id, i.indicator_name, v.year, v.value
FROM {CATALOG}.silver.indicator_values v
JOIN {CATALOG}.silver.countries c USING (country_iso3)
JOIN {CATALOG}.silver.indicators i USING (indicator_id)
""")

pivot_cols = ",\n  ".join(f"max(CASE WHEN v.indicator_id = '{code}' THEN v.value END) AS {col}" for code, col in COLUMNS.items())
spark.sql(f"""
CREATE OR REPLACE TABLE {CATALOG}.gold.country_indicator_wide
COMMENT 'One row per country and year with one column per demo indicator; values are as published by the World Bank'
AS SELECT
  c.country_iso3, c.country_name, c.region, c.income_level, v.year,
  {pivot_cols}
FROM {CATALOG}.silver.indicator_values v
JOIN {CATALOG}.silver.countries c USING (country_iso3)
GROUP BY c.country_iso3, c.country_name, c.region, c.income_level, v.year
""")

# COMMAND ----------

# Column comments come from the indicator names, so Genie and the agents see units and meaning.
names = {r.indicator_id: r.indicator_name for r in spark.table(f"{CATALOG}.silver.indicators").collect()}
for code, col in COLUMNS.items():
    spark.sql(f"ALTER TABLE {CATALOG}.gold.country_indicator_wide ALTER COLUMN {col} COMMENT '{sql_str(names.get(code, code))} [{code}]'")
for col, text in {
    "country_iso3": "ISO 3166-1 alpha-3 country code",
    "country_name": "Country name",
    "region": "World Bank region",
    "income_level": "World Bank income group",
    "year": "Calendar year",
}.items():
    spark.sql(f"ALTER TABLE {CATALOG}.gold.country_indicator_wide ALTER COLUMN {col} COMMENT '{text}'")

for table in ("gold.indicator_facts", "gold.country_indicator_wide"):
    try:
        spark.sql(f"ALTER TABLE {CATALOG}.{table} SET TAGS {TAGS}")
    except Exception as e:  # tags are a governance nicety; report, do not fail the load
        print(f"WARNING: could not tag {table}: {e}")

# COMMAND ----------

summary = spark.sql(f"""
SELECT count(*) AS rows, count(DISTINCT country_iso3) AS countries, min(year) AS first_year, max(year) AS last_year
FROM {CATALOG}.gold.country_indicator_wide
""").first()
print(summary.asDict())
assert summary.rows > 0, "gold.country_indicator_wide is empty"
