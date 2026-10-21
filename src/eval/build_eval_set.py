# Databricks notebook source
# MAGIC %md
# MAGIC # Build the evaluation set (`ml.eval_questions`)
# MAGIC About 20 questions in four groups, each with the facts a correct answer must contain:
# MAGIC - **data**: expected values are computed here from `gold.country_indicator_wide`, so they always match the data.
# MAGIC - **reports**: facts read from the indexed report passages (title, year and page noted beside each).
# MAGIC - **both**: a number plus a report finding.
# MAGIC - **off_topic**: the agent must decline.

# COMMAND ----------

dbutils.widgets.text("catalog", "wb_demo")
CATALOG = dbutils.widgets.get("catalog")
T = f"{CATALOG}.gold.country_indicator_wide"


def value(iso3, column, year):
    row = spark.sql(f"SELECT {column} AS v FROM {T} WHERE country_iso3 = '{iso3}' AND year = {year}").first()
    if row is None or row.v is None:
        raise ValueError(f"no {column} for {iso3} {year}")
    return row.v


def latest(iso3, column):
    return spark.sql(f"""SELECT year, {column} AS v FROM {T} WHERE country_iso3 = '{iso3}' AND {column} IS NOT NULL
                         ORDER BY year DESC LIMIT 1""").first()

# COMMAND ----------

rows = []


def add(group, question, facts):
    rows.append({"group": group, "question": question, "expected_facts": facts})


# --- data: single values and simple comparisons (computed from the gold table) ---
add("data", "What was Kenya's access to electricity in 2022?",
    [f"Kenya's access to electricity in 2022 was {value('KEN', 'electricity_access_pct', 2022):.1f}% of the population"])
add("data", "What was India's total population in 2020?",
    [f"India's population in 2020 was about {value('IND', 'population', 2020) / 1e9:.2f} billion"])
add("data", "What was Brazil's GDP per capita in current US dollars in 2023?",
    [f"Brazil's GDP per capita in 2023 was about US${value('BRA', 'gdp_per_capita_usd', 2023):,.0f}"])
add("data", "What was Nigeria's under-5 mortality rate in 2015?",
    [f"Nigeria's under-5 mortality rate in 2015 was {value('NGA', 'under5_mortality_per_1000', 2015):.1f} per 1,000 live births"])
add("data", "What was life expectancy at birth in Ghana in 2022?",
    [f"Life expectancy at birth in Ghana in 2022 was about {value('GHA', 'life_expectancy_years', 2022):.1f} years"])
e = latest("ETH", "electricity_access_pct")
add("data", "How has Ethiopia's access to electricity changed since 2010?",
    [f"Ethiopia's access to electricity was {value('ETH', 'electricity_access_pct', 2010):.1f}% in 2010",
     f"It was {e.v:.1f}% in {e.year}"])
top = spark.sql(f"SELECT country_name FROM {T} WHERE year = 2022 ORDER BY life_expectancy_years DESC NULLS LAST LIMIT 1").first()
add("data", "Which country in the data had the highest life expectancy at birth in 2022?",
    [f"{top.country_name} had the highest life expectancy in 2022"])
add("data", "Compare CO2 emissions per capita in India and Indonesia in 2020.",
    [f"India emitted about {value('IND', 'co2_per_capita_t', 2020):.2f} tonnes of CO2 per person in 2020",
     f"Indonesia emitted about {value('IDN', 'co2_per_capita_t', 2020):.2f} tonnes of CO2 per person in 2020"])
pov = spark.sql(f"""
WITH p AS (SELECT country_name, year, poverty_3usd_day_pct AS v FROM {T} WHERE poverty_3usd_day_pct IS NOT NULL AND year >= 2000),
f AS (SELECT country_name, min(year) AS y0, min_by(v, year) AS v0, max(year) AS y1, max_by(v, year) AS v1 FROM p GROUP BY country_name)
SELECT country_name FROM f WHERE y0 <= 2005 AND y1 > y0 ORDER BY v0 - v1 DESC LIMIT 3""").collect()
add("data", "Which three countries in the data reduced extreme poverty the most since 2000?",
    [f"The three countries are {', '.join(r.country_name for r in pov)}"])

# --- reports: facts taken from indexed passages (source noted for each) ---
add("reports", "What does the World Bank identify as the main constraints on growth in Bangladesh?",
    ["Declining trade competitiveness", "A weak or vulnerable financial (banking) sector",
     "Unbalanced and inefficient urbanization"])  # Bangladesh CEM "Change of Fabric", 2022, pp. 35-36
add("reports", "According to the World Bank, what role do services play in Kenya's economic growth?",
    ["Most of Kenya's recent economic growth has been in services",
     "Services have accounted for the bulk of new jobs"])  # Kenya CEM 2023 Overview, p. 8
add("reports", "What policies does the World Bank say weaken poverty reduction in Nigeria?",
    ["Multiple exchange rates", "Trade restrictions such as import bans and the 2019 border closure"])  # Nigeria Poverty Assessment 2022, p. 12
add("reports", "According to the World Bank, how many workers in South Africa could lose jobs from decarbonization?",
    ["About 300,000 workers in high-emitting sectors could lose their jobs"])  # South Africa CCDR Executive Summary 2022, p. 7
add("reports", "What does the World Bank say about Indonesia's dependence on coal?",
    ["Indonesia is the world's largest coal exporter", "Coal exports are about 2 percent of GDP",
     "Indonesia committed to net-zero emissions by 2060"])  # Indonesia Poverty Assessment 2023, p. 20
add("reports", "Why does the World Bank say Pakistan is stuck in a cycle of repeated external crises?",
    ["Distortions in the economy have led to a misallocation of resources"])  # Pakistan CEM 2022 Executive Summary, p. 12

# --- both: a number and a report finding ---
b0, b1 = value("BGD", "gdp_per_capita_usd", 2010), latest("BGD", "gdp_per_capita_usd")
add("both", "How has Bangladesh's GDP per capita changed since 2010, and what constraints on growth does the World Bank identify?",
    [f"Bangladesh's GDP per capita was about US${b0:,.0f} in 2010", f"It was about US${b1.v:,.0f} in {b1.year}",
     "Constraints include declining trade competitiveness, a weak financial sector and unbalanced urbanization"])
k0, k1 = value("KEN", "electricity_access_pct", 2010), latest("KEN", "electricity_access_pct")
add("both", "What was Kenya's access to electricity in 2010 and the latest year, and what does the World Bank say about the role of services in Kenya's growth?",
    [f"Kenya's access to electricity was {k0:.1f}% in 2010", f"It was {k1.v:.1f}% in {k1.year}",
     "Services have driven most of Kenya's recent growth and new jobs"])

# --- off_topic: the agent must decline ---
for q in ["What is the weather in Paris today?", "Give me a recipe for chocolate cake.",
          "Who won the last football World Cup?"]:
    add("off_topic", q, ["The assistant declines because it only answers questions about World Bank development data"])

# COMMAND ----------

import json

from pyspark.sql import Row

df = spark.createDataFrame([Row(group=r["group"], question=r["question"], expected_facts=json.dumps(r["expected_facts"]))
                            for r in rows])
df.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(f"{CATALOG}.ml.eval_questions")
spark.sql(f"COMMENT ON TABLE {CATALOG}.ml.eval_questions IS 'Evaluation set for the World Bank agent: question, group, expected facts (JSON list)'")
display(df.groupBy("group").count())
print(f"{len(rows)} questions written to {CATALOG}.ml.eval_questions")
