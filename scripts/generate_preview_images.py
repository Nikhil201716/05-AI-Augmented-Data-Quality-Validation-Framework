"""
generate_preview_images.py
---------------------------
Renders static PNG chart previews (matplotlib/seaborn) straight from the
warehouse + reports this pipeline itself produced, for the README. This
build environment has no display to screenshot the live Streamlit app,
so these are real charts built from the exact same data instead.

Output: ../screenshots/*.png
"""

import json
import sqlite3
from pathlib import Path

import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "database" / "warehouse.duckdb"
REPORTS_DIR = ROOT / "reports"
OUT_DIR = ROOT / "screenshots"
OUT_DIR.mkdir(exist_ok=True)

sns.set_theme(style="whitegrid")
NAVY, ACCENT, RED, GOLD = "#1F3A5F", "#2E6F40", "#C0392B", "#E1A100"

conn = duckdb.connect(str(DB_PATH), read_only=True)
orders = conn.execute("SELECT * FROM main.fct_orders").fetchdf()
conn.close()
orders["order_date"] = pd.to_datetime(orders["order_timestamp"]).dt.date

with open(ROOT / "dbt_project" / "target" / "test_run_results.json", encoding="utf-8") as f:
    dbt_raw = json.load(f)
with open(ROOT / "dbt_project" / "target" / "manifest.json", encoding="utf-8") as f:
    manifest = json.load(f)
nodes = manifest.get("nodes", {})
dbt_rows = []
for r in dbt_raw["results"]:
    name = nodes.get(r["unique_id"], {}).get("name") or r["unique_id"].split(".")[-1]
    dbt_rows.append({"test_name": name, "status": r["status"].upper()})
dbt_df = pd.DataFrame(dbt_rows)

with open(REPORTS_DIR / "pandera_validation_results.json", encoding="utf-8") as f:
    pandera_results = json.load(f)
pandera_df = pd.DataFrame(pandera_results["checks"])

# ------------------------------------------------------------------
# 1. KPI summary
# ------------------------------------------------------------------
fig, axes = plt.subplots(1, 4, figsize=(13, 2.2))
cards = [
    ("Orders in Warehouse", f"{len(orders):,}"),
    ("dbt Tests Passed", f"{(dbt_df.status == 'PASS').sum()}/{len(dbt_df)}"),
    ("Pandera Checks Passed", f"{pandera_results['passed']}/{pandera_results['total_checks']}"),
    ("Orphaned-Product Orders", f"{int(orders.is_orphan_product.sum())}"),
]
for ax, (label, value) in zip(axes, cards):
    ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 0), 1, 1, color=NAVY, transform=ax.transAxes, zorder=0))
    ax.text(0.5, 0.68, label, ha="center", va="center", color="white", fontsize=10, transform=ax.transAxes)
    ax.text(0.5, 0.32, value, ha="center", va="center", color="white", fontsize=15, fontweight="bold", transform=ax.transAxes)
fig.suptitle("AI-Augmented Data Quality Platform - Key Metrics", fontsize=12, color=NAVY, y=1.08)
plt.tight_layout()
plt.savefig(OUT_DIR / "01_kpi_summary.png", dpi=150, bbox_inches="tight")
plt.close()

# ------------------------------------------------------------------
# 2. dbt test results + Pandera results side by side
# ------------------------------------------------------------------
fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
status_order = ["PASS", "WARN", "FAIL"]
counts1 = dbt_df.status.value_counts().reindex(status_order).fillna(0)
colors1 = [ACCENT, GOLD, RED]
axes[0].bar(counts1.index, counts1.values, color=colors1)
axes[0].set_title("dbt Test Results (27 tests)", color=NAVY, fontweight="bold")
axes[0].set_ylabel("Count")

counts2 = pandera_df.status.value_counts().reindex(["PASS", "FAIL"]).fillna(0)
axes[1].bar(counts2.index, counts2.values, color=[ACCENT, RED])
axes[1].set_title("Pandera Statistical Checks (5 checks)", color=NAVY, fontweight="bold")
plt.tight_layout()
plt.savefig(OUT_DIR / "02_test_results.png", dpi=150, bbox_inches="tight")
plt.close()

# ------------------------------------------------------------------
# 3. Daily order volume + DQ flag rate (the incident-detection chart)
# ------------------------------------------------------------------
daily = orders.groupby("order_date").agg(
    orders=("order_id", "count"),
).reset_index()
flag_any = orders["is_orphan_product"] | orders["is_missing_customer"] | orders["is_invalid_quantity"]
orders["_any_flag"] = flag_any
daily_flags = orders.groupby("order_date")["_any_flag"].mean().reset_index()
daily = daily.merge(daily_flags, on="order_date")
daily["flag_rate_pct"] = daily["_any_flag"] * 100

fig, ax1 = plt.subplots(figsize=(11, 4.8))
ax1.bar(daily.order_date, daily.orders, color=NAVY, alpha=0.8, label="Order Volume")
ax1.set_ylabel("Orders")
ax2 = ax1.twinx()
ax2.plot(daily.order_date, daily.flag_rate_pct, color=RED, linewidth=2, label="DQ Flag Rate %")
ax2.set_ylabel("DQ Flag Rate %")
fig.suptitle("Daily Order Volume & Data-Quality Flag Rate\n(the spike on 2026-06-17 is the injected incident)",
             color=NAVY, fontsize=12, fontweight="bold")
lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
plt.tight_layout()
plt.savefig(OUT_DIR / "03_incident_detection.png", dpi=150, bbox_inches="tight")
plt.close()

print("Saved 3 preview images to", OUT_DIR)
