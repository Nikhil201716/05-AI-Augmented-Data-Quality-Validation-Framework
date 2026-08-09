"""
build_knowledge_base.py
------------------------
Assembles the knowledge base the AI Data Quality Copilot retrieves from,
and embeds it into a persistent ChromaDB collection using Chroma's
built-in ONNX MiniLM embedding function (no torch/sentence-transformers
needed - a deliberate choice on RAM-constrained hardware, see README).

Four kinds of documents go in, each written to answer a different kind
of real question a teammate would actually ask:

  1. dbt test results       -> "why did X fail / did X pass?"
  2. Pandera check results  -> "does anything look statistically off?"
  3. Model documentation    -> "what does model Y even contain?"
  4. A root-cause runbook   -> "what usually causes an orphaned product?"
  5. A computed incident summary, built from REAL query results against
     the warehouse (not hand-written), so the copilot's most detailed
     answer is grounded in the actual data, not a canned story.

Run AFTER: scripts/generate_data.py, scripts/load_raw_to_duckdb.py,
dbt run, dbt test, validation/pandera_checks.py.
"""

import json
from pathlib import Path

import chromadb
import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DBT_TARGET = ROOT / "dbt_project" / "target"
REPORTS_DIR = ROOT / "reports"
DB_PATH = ROOT / "database" / "warehouse.duckdb"
CHROMA_PATH = ROOT / "rag" / "knowledge_base" / "chroma_store"
CHROMA_PATH.parent.mkdir(parents=True, exist_ok=True)

documents = []   # list of (id, text, metadata)


def add_doc(doc_id, text, **metadata):
    documents.append((doc_id, text.strip(), metadata))


# ============================================================================
# 1. dbt test results
# ============================================================================
DBT_TEST_EXPLANATIONS = {
    "assert_no_extreme_line_totals": (
        "Checks that every order's line_total falls between $0.50 and $5000, a plausible "
        "range for the NorthPeak Outdoor Gear catalog (products range roughly $15-$290). "
        "A failure here almost always indicates a PRICING BUG - most commonly a unit-price "
        "multiplier applied incorrectly upstream (e.g. a price stored in cents being read as "
        "dollars, or vice versa) - not a normal data-entry typo."
    ),
    "assert_valid_order_dates": (
        "Checks that no order is dated before 2025-01-01 or in the future. A failure would "
        "suggest a timezone bug or a corrupted timestamp field upstream."
    ),
    "not_null_stg_orders_customer_id": (
        "Checks that every order has a customer_id. This is set to WARN severity rather than "
        "hard-fail, because a small background rate of missing customer references can happen "
        "from anonymous/guest checkouts. A sudden SPIKE in this warning's count on one specific "
        "day (rather than a steady background rate) points to a CRM/session-linking bug in the "
        "order-capture system on that day, not guest checkouts."
    ),
    "relationships_fct_orders_product_id__product_id__ref_stg_products_": (
        "Checks that every order's product_id actually exists in the product catalog "
        "(stg_products). A failure means orders reference a PRODUCT THAT DOESN'T EXIST - "
        "typically caused by a catalog sync issue: either the product was deleted/retired "
        "after orders referenced it, or the order-capture system wrote a product_id before "
        "the catalog table finished syncing that day."
    ),
}

try:
    with open(DBT_TARGET / "manifest.json", "r", encoding="utf-8") as f:
        manifest = json.load(f)
    manifest_nodes = manifest.get("nodes", {})
except FileNotFoundError:
    manifest_nodes = {}

try:
    with open(DBT_TARGET / "test_run_results.json", "r", encoding="utf-8") as f:
        run_results = json.load(f)
    for result in run_results.get("results", []):
        unique_id = result["unique_id"]
        node_name = manifest_nodes.get(unique_id, {}).get("name") or unique_id.split(".")[-1]
        status = result["status"].upper()
        n_failing = result.get("failures", 0) or 0
        explanation = DBT_TEST_EXPLANATIONS.get(node_name, "")
        text = (
            f"dbt test '{node_name}': status = {status}"
            + (f", {n_failing} failing row(s)." if status != "PASS" else ", 0 failing rows.")
            + (f" {explanation}" if explanation else "")
        )
        add_doc(f"dbt_test_{node_name}", text, source="dbt_test", status=status, test_name=node_name)
    print(f"Loaded {len(run_results.get('results', []))} dbt test results")
except FileNotFoundError:
    print("WARNING: dbt test_run_results.json not found - run `dbt test` first")

# ============================================================================
# 2. Pandera validation results
# ============================================================================
try:
    with open(REPORTS_DIR / "pandera_validation_results.json", "r", encoding="utf-8") as f:
        pandera_results = json.load(f)
    for check in pandera_results["checks"]:
        text = (
            f"Pandera statistical check '{check['check_name']}' on {check['layer']}: "
            f"status = {check['status']}. {check['detail']}"
        )
        add_doc(f"pandera_{check['check_name']}", text, source="pandera",
                 status=check["status"], check_name=check["check_name"])
    print(f"Loaded {len(pandera_results['checks'])} Pandera check results")
except FileNotFoundError:
    print("WARNING: pandera_validation_results.json not found - run validation/pandera_checks.py first")

# ============================================================================
# 3. Model documentation (hand-written, matches schema.yml descriptions)
# ============================================================================
MODEL_DOCS = {
    "stg_customers": "Staging model: one row per customer, lightly cleaned (trimmed/lowercased email, cast types) from raw_customers. No business logic.",
    "stg_products": "Staging model: one row per product from raw_products, listing name, category, unit_price, and cost_price for the NorthPeak Outdoor Gear catalog.",
    "stg_orders": "Staging model: one row per order, DEDUPLICATED on order_id (keeping the first occurrence). Rows with a missing customer or an invalid quantity are kept and flagged (is_missing_customer, is_invalid_quantity), never silently dropped.",
    "stg_payments": "Staging model: one row per payment from raw_payments.",
    "int_orders_enriched": "Intermediate model: orders LEFT JOINed to customer and product context. Computes line_total. Flags is_orphan_product for orders referencing a product_id that doesn't exist in the catalog.",
    "fct_orders": "Mart (final table): the business-ready, order-grain fact table. Adds the payment join (has_payment, amount_mismatch) on top of int_orders_enriched. This is the table a BI tool or analyst should query.",
    "dim_customers": "Mart (final table): one row per customer with lifetime_orders and lifetime_value computed from all their orders.",
    "dim_products": "Mart (final table): one row per product with times_ordered, total_revenue, and margin computed from all its orders.",
}
for model, desc in MODEL_DOCS.items():
    add_doc(f"model_doc_{model}", f"dbt model '{model}': {desc}", source="model_doc", model_name=model)
print(f"Loaded {len(MODEL_DOCS)} model documentation entries")

# ============================================================================
# 4. Root-cause runbook (general knowledge, not tied to one specific run)
# ============================================================================
RUNBOOK = [
    ("is_orphan_product", "An order references a product_id that doesn't exist in the product catalog. "
     "Typical causes: (a) the product was deleted/retired from the catalog after orders referenced it, "
     "(b) a catalog sync job ran late and the order-capture system wrote orders before the new catalog "
     "was available, (c) a manual data-entry error in the product_id field."),
    ("is_missing_customer", "An order has no customer_id at all. Typical causes: (a) a genuine guest/anonymous "
     "checkout flow (expected at a low background rate), (b) a session-linking bug in the checkout service "
     "that fails to attach the logged-in customer's ID to the order record, (c) a batch-job retry that wrote "
     "a partial record."),
    ("is_invalid_quantity", "An order has a quantity that is zero, negative, or implausibly large (>100). "
     "Typical causes: (a) a cart-service bug allowing a negative adjustment through, (b) a race condition "
     "during a retried write, (c) a load-testing or bot script accidentally hitting the production endpoint."),
    ("amount_mismatch", "A payment's amount doesn't match the order's computed line_total. Typical causes: "
     "(a) a discount or coupon applied at checkout that wasn't reflected back in the order record, "
     "(b) a currency conversion applied inconsistently, (c) a pricing change between order placement and "
     "payment capture."),
    ("daily volume anomaly", "A day's total order count deviates significantly (>2.5 standard deviations) "
     "from the recent daily average. This can indicate either a genuine business event (a promotion, a "
     "marketing campaign) or a technical issue (a retry storm, duplicate webhook deliveries, a bot/scraper "
     "hitting checkout). Cross-reference with the data-quality flag rates on that same day to tell the two "
     "apart - a spike with elevated is_orphan_product/is_missing_customer rates points to a technical issue, "
     "not a genuine sales spike."),
]
for flag, explanation in RUNBOOK:
    add_doc(f"runbook_{flag.replace(' ', '_')}", f"Root-cause runbook - '{flag}': {explanation}",
             source="runbook", topic=flag)
print(f"Loaded {len(RUNBOOK)} runbook entries")

# ============================================================================
# 5. Computed incident summary - built from REAL warehouse query results
# ============================================================================
conn = duckdb.connect(str(DB_PATH), read_only=True)
incident = conn.execute("""
    SELECT
        order_date,
        COUNT(*) AS total_orders,
        SUM(CASE WHEN is_missing_customer THEN 1 ELSE 0 END) AS missing_customer_count,
        SUM(CASE WHEN is_orphan_product THEN 1 ELSE 0 END) AS orphan_product_count,
        SUM(CASE WHEN is_invalid_quantity THEN 1 ELSE 0 END) AS invalid_quantity_count,
        SUM(CASE WHEN amount_mismatch THEN 1 ELSE 0 END) AS amount_mismatch_count
    FROM (SELECT *, CAST(order_timestamp AS DATE) AS order_date FROM main.fct_orders)
    WHERE is_incident_day = true
    GROUP BY order_date
""").fetchdf()

avg_daily = conn.execute("""
    SELECT AVG(cnt) AS avg_daily_orders FROM (
        SELECT CAST(order_timestamp AS DATE) AS d, COUNT(*) AS cnt
        FROM main.fct_orders GROUP BY d
    )
""").fetchdf().iloc[0]["avg_daily_orders"]
conn.close()

if len(incident):
    row = incident.iloc[0]
    text = (
        f"KNOWN INCIDENT SUMMARY - {row['order_date']}: This day saw {int(row['total_orders'])} orders "
        f"versus a {avg_daily:.0f}-order daily average across the full dataset - a significant volume spike. "
        f"Within this day's orders: {int(row['missing_customer_count'])} had a missing customer_id, "
        f"{int(row['orphan_product_count'])} referenced a product_id not present in the catalog, "
        f"{int(row['invalid_quantity_count'])} had an invalid quantity (zero, negative, or >100), and "
        f"{int(row['amount_mismatch_count'])} had a payment amount that didn't match the order's line_total. "
        f"This pattern - a volume spike combined with elevated data-quality flag rates concentrated on a "
        f"single day - is consistent with a batch-job or deployment bug on that date, not a genuine "
        f"organic sales spike (see runbook entry 'daily volume anomaly')."
    )
    add_doc("known_incident_summary", text, source="incident_summary")
    print("Built 1 computed incident summary from live warehouse data")

# ============================================================================
# Embed and store in ChromaDB
# ============================================================================
client = chromadb.PersistentClient(path=str(CHROMA_PATH))
try:
    client.delete_collection("data_quality_knowledge_base")
except Exception:
    pass
collection = client.create_collection("data_quality_knowledge_base")

collection.add(
    ids=[d[0] for d in documents],
    documents=[d[1] for d in documents],
    metadatas=[d[2] for d in documents],
)

print(f"\nIndexed {len(documents)} documents into ChromaDB at {CHROMA_PATH}")
