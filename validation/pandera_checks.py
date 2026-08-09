"""
pandera_checks.py
------------------
Statistical and business-rule validation, deliberately covering DIFFERENT
ground than dbt's schema tests rather than duplicating them:

  - dbt tests answer: "is this column ever null/duplicated?", "does this
    foreign key always resolve?" - structural, row-level, deterministic.
  - Pandera here answers: "is this value plausible?", "does today's
    volume/behavior look statistically normal compared to recent
    history?" - distributional, comparative, judgment-based checks that
    a simple not_null/unique test can't express.

This is exactly the kind of two-tool setup a real data platform runs:
dbt owns structural correctness, a statistical validator owns "does this
look right" - and this project intentionally keeps both, because a real
pricing bug (Section: extreme_unit_price) or a real traffic anomaly
(Section: daily volume) can pass every structural test while still being
very wrong.

NOTE ON TOOLING: this project originally targeted Great Expectations for
this layer (matching common industry usage), but GX's latest available
release in this environment pins numpy<2.0, which cannot build from
source on Python 3.14 here (no working C compiler). Pandera is a modern,
actively maintained, increasingly widely used alternative for exactly
this use case - a real, defensible substitution, not a downgrade in
rigor. See README Section 9 for the full note.

Output:
  - reports/pandera_validation_results.json  (structured, for the RAG
    knowledge base and the dashboard)
  - reports/pandera_validation_summary.md    (human-readable)
"""

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "warehouse.duckdb"
REPORTS_DIR = ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

conn = duckdb.connect(str(DB_PATH), read_only=True)
orders = conn.execute("SELECT * FROM main.fct_orders").fetchdf()
customers = conn.execute("SELECT * FROM main.stg_customers").fetchdf()
conn.close()

results = []


def record(check_name, layer, passed, detail, n_failing=0):
    results.append({
        "check_name": check_name,
        "layer": layer,
        "status": "PASS" if passed else "FAIL",
        "detail": detail,
        "n_failing_rows": int(n_failing),
    })
    icon = "PASS" if passed else "FAIL"
    print(f"[{icon}] {check_name}: {detail}")


# ============================================================================
# 1. Schema-level statistical checks on fct_orders (row-level, but checking
#    PLAUSIBILITY, not just presence - complementary to dbt's not_null/unique)
# ============================================================================
order_schema = DataFrameSchema({
    "quantity": Column(int, Check.in_range(1, 20), nullable=False),
    "unit_price": Column(float, Check.in_range(1.0, 500.0), nullable=False),
    "discount_pct": Column(float, Check.in_range(0.0, 0.30), nullable=False),
}, strict=False)

try:
    order_schema.validate(orders, lazy=True)
    record("plausible_value_ranges", "fct_orders", True,
           "quantity, unit_price, and discount_pct all fall within plausible business ranges.")
except pa.errors.SchemaErrors as e:
    fail_cases = e.failure_cases
    n = len(fail_cases)
    by_check = fail_cases.groupby("check")["index"].count().to_dict()
    record("plausible_value_ranges", "fct_orders", False,
           f"{n} value(s) fell outside plausible ranges: {by_check}", n)

# ============================================================================
# 2. Email format check on customers (a check dbt's not_null wouldn't catch -
#    a non-null but malformed email is still a data quality problem)
# ============================================================================
email_schema = DataFrameSchema({
    "email": Column(str, Check.str_matches(r"^[^@\s]+@[^@\s]+\.[^@\s]+$"), nullable=False),
})
try:
    email_schema.validate(customers, lazy=True)
    record("email_format_valid", "stg_customers", True, "All customer emails match a valid email pattern.")
except pa.errors.SchemaErrors as e:
    n = len(e.failure_cases)
    record("email_format_valid", "stg_customers", False, f"{n} email(s) failed format validation.", n)

# ============================================================================
# 3. Daily order volume anomaly detection (z-score) - a comparative,
#    time-aware check no single-row schema test can express
# ============================================================================
orders["order_date"] = pd.to_datetime(orders["order_timestamp"]).dt.date
daily_counts = orders.groupby("order_date").size().reset_index(name="order_count")
mean_vol, std_vol = daily_counts["order_count"].mean(), daily_counts["order_count"].std()
daily_counts["z_score"] = (daily_counts["order_count"] - mean_vol) / std_vol
anomalous_days = daily_counts[daily_counts["z_score"].abs() > 2.5]

if len(anomalous_days) == 0:
    record("daily_volume_anomaly_detection", "fct_orders (time series)", True,
           f"No day's order volume deviated more than 2.5 standard deviations from the "
           f"{mean_vol:.0f}-order daily average.")
else:
    days_str = ", ".join(f"{r.order_date} ({r.order_count} orders, z={r.z_score:.2f})"
                          for r in anomalous_days.itertuples())
    record("daily_volume_anomaly_detection", "fct_orders (time series)", False,
           f"{len(anomalous_days)} day(s) had statistically anomalous order volume vs. "
           f"the {mean_vol:.0f}-order average (std={std_vol:.0f}): {days_str}", len(anomalous_days))

# ============================================================================
# 4. Missing-customer RATE threshold (aggregate view of the same issue dbt
#    flags at the row level - useful because a rate crossing a threshold is
#    a different kind of alert than "N individual rows are null")
# ============================================================================
missing_rate = orders["is_missing_customer"].mean()
THRESHOLD = 0.02
if missing_rate <= THRESHOLD:
    record("missing_customer_rate_threshold", "fct_orders", True,
           f"Missing-customer rate {missing_rate:.2%} is within the {THRESHOLD:.0%} acceptable threshold.")
else:
    record("missing_customer_rate_threshold", "fct_orders", False,
           f"Missing-customer rate {missing_rate:.2%} exceeds the {THRESHOLD:.0%} acceptable threshold "
           f"({int(orders['is_missing_customer'].sum())} of {len(orders):,} orders).",
           int(orders["is_missing_customer"].sum()))

# ============================================================================
# 5. Orphaned-product rate threshold (aggregate view, same idea as #4)
# ============================================================================
orphan_rate = orders["is_orphan_product"].mean()
THRESHOLD_ORPHAN = 0.01
if orphan_rate <= THRESHOLD_ORPHAN:
    record("orphan_product_rate_threshold", "fct_orders", True,
           f"Orphaned-product rate {orphan_rate:.2%} is within the {THRESHOLD_ORPHAN:.0%} acceptable threshold.")
else:
    record("orphan_product_rate_threshold", "fct_orders", False,
           f"Orphaned-product rate {orphan_rate:.2%} exceeds the {THRESHOLD_ORPHAN:.0%} acceptable threshold "
           f"({int(orders['is_orphan_product'].sum())} of {len(orders):,} orders).",
           int(orders["is_orphan_product"].sum()))

# ============================================================================
# Save
# ============================================================================
summary = {
    "total_checks": len(results),
    "passed": sum(1 for r in results if r["status"] == "PASS"),
    "failed": sum(1 for r in results if r["status"] == "FAIL"),
    "checks": results,
}
with open(REPORTS_DIR / "pandera_validation_results.json", "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=2)

with open(REPORTS_DIR / "pandera_validation_summary.md", "w", encoding="utf-8") as f:
    f.write("# Pandera Statistical Validation Results\n\n")
    f.write(f"**{summary['passed']}/{summary['total_checks']} checks passed**\n\n")
    for r in results:
        f.write(f"## {r['check_name']} ({r['layer']}) - {r['status']}\n{r['detail']}\n\n")

print(f"\n{summary['passed']}/{summary['total_checks']} Pandera checks passed. "
      f"Report saved to {REPORTS_DIR / 'pandera_validation_results.json'}")
