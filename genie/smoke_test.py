"""Phase 1 check: Genie must answer 5 numeric questions with the value the gold table holds.

Each expected value is computed independently with SQL, then looked for in Genie's text answer.
Usage: python3 genie/smoke_test.py <space_id> <warehouse_id>
"""
import json
import subprocess
import sys

SPACE, WAREHOUSE = sys.argv[1], sys.argv[2]
T = "wb_demo.gold.country_indicator_wide"
CASES = [
    ("What was Kenya's access to electricity in 2022?",
     f"SELECT electricity_access_pct FROM {T} WHERE country_iso3='KEN' AND year=2022", 1),
    ("What was India's total population in 2020?",
     f"SELECT population FROM {T} WHERE country_iso3='IND' AND year=2020", 0),
    ("What was Brazil's GDP per capita in current US dollars in 2023?",
     f"SELECT gdp_per_capita_usd FROM {T} WHERE country_iso3='BRA' AND year=2023", 0),
    ("Which country had the highest life expectancy at birth in 2022?",
     f"SELECT country_name FROM {T} WHERE year=2022 ORDER BY life_expectancy_years DESC NULLS LAST LIMIT 1", None),
    ("What was Nigeria's under-5 mortality rate per 1,000 live births in 2015?",
     f"SELECT under5_mortality_per_1000 FROM {T} WHERE country_iso3='NGA' AND year=2015", 1),
]


def cli(*args):
    out = subprocess.run(["databricks", *args, "-o", "json"], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def sql(statement):
    body = json.dumps({"warehouse_id": WAREHOUSE, "statement": statement, "wait_timeout": "50s"})
    d = cli("api", "post", "/api/2.0/sql/statements", "--json", body)
    assert d["status"]["state"] == "SUCCEEDED", d["status"]
    return d["result"]["data_array"][0][0]


def variants(value, decimals):
    """Ways Genie may print the value: plain, rounded, with thousands separators, or in millions/billions."""
    if decimals is None:
        return {value}
    v = float(value)
    out = {f"{v:.{decimals}f}", f"{v:,.{decimals}f}", f"{v:.2f}", f"{v:,.2f}", f"{round(v)}", f"{round(v):,}"}
    for scale, word in ((1e9, "billion"), (1e6, "million")):
        if v >= scale:
            out |= {f"{v / scale:.1f} {word}", f"{v / scale:.2f} {word}"}
    return out


passed = 0
for question, truth_sql, decimals in CASES:
    expected = sql(truth_sql)
    msg = cli("genie", "start-conversation", SPACE, question)
    answer = " ".join(a["text"]["content"] for a in msg.get("attachments", []) if "text" in a)
    plain = answer.replace("**", "")
    ok = any(v in plain for v in variants(expected, decimals))
    passed += ok
    print(f"{'PASS' if ok else 'FAIL'} | {question}\n       expected {expected} | genie: {plain[:200]}")

print(f"{passed}/{len(CASES)} passed")
sys.exit(0 if passed == len(CASES) else 1)
