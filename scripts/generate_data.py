"""
generate_data.py
-----------------
Generates a fresh SYNTHETIC multi-table e-commerce dataset for "NorthPeak
Outdoor Gear" (a fictional outdoor/camping equipment retailer) - the raw
layer this project's dbt models transform and its validation suite
checks. 4 raw source tables: customers, products, orders, payments.

Deliberately includes one clear "incident day" where a simulated batch
job bug corrupts a chunk of that day's orders (nulls, duplicates,
orphaned product references, a pricing bug producing extreme order
values) - this is what gives the dbt tests, the Pandera validation
suite, and later the AI Data Quality Copilot something real and
specific to catch and explain, not just clean data with no story.

No real customer, product, or company data is used anywhere.

Output: data/raw_customers.csv, raw_products.csv, raw_orders.csv, raw_payments.csv
"""

import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

SEED = 42
rng = np.random.default_rng(SEED)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

START_DATE = datetime(2026, 3, 1)
END_DATE = datetime(2026, 7, 29)
DAYS = pd.date_range(START_DATE, END_DATE, freq="D")
INCIDENT_DAY = datetime(2026, 6, 17)   # the simulated batch-job bug date

# ----------------------------------------------------------------------
# 1. Customers
# ----------------------------------------------------------------------
N_CUSTOMERS = 4000
COUNTRIES = ["USA", "Canada", "UK", "Germany", "Australia", "France"]
FIRST = ["Alex", "Jordan", "Taylor", "Sam", "Casey", "Morgan", "Riley", "Jamie",
         "Avery", "Quinn", "Drew", "Skyler", "Reese", "Rowan", "Emerson"]
LAST = ["Turner", "Brooks", "Rivera", "Bennett", "Coleman", "Foster", "Hayes",
        "Reed", "Stone", "Ward", "Nash", "Blake", "Cross", "Lane", "Pierce"]

customer_ids = [f"CUST{20000+i}" for i in range(N_CUSTOMERS)]
customers = pd.DataFrame({
    "customer_id": customer_ids,
    "email": [f"{rng.choice(FIRST).lower()}.{rng.choice(LAST).lower()}{rng.integers(1,999)}@example.com"
               for _ in range(N_CUSTOMERS)],
    "full_name": [f"{rng.choice(FIRST)} {rng.choice(LAST)}" for _ in range(N_CUSTOMERS)],
    "signup_date": [(START_DATE - timedelta(days=int(d))).date().isoformat()
                    for d in rng.integers(0, 900, size=N_CUSTOMERS)],
    "country": rng.choice(COUNTRIES, size=N_CUSTOMERS, p=[0.42, 0.14, 0.16, 0.12, 0.08, 0.08]),
    "marketing_opt_in": rng.choice([1, 0], size=N_CUSTOMERS, p=[0.62, 0.38]),
})
customers.to_csv(DATA_DIR / "raw_customers.csv", index=False)
print(f"Customers: {len(customers)} -> raw_customers.csv")

# ----------------------------------------------------------------------
# 2. Products
# ----------------------------------------------------------------------
PRODUCTS = [
    ("Trailhead 2P Tent", "Shelter", 189.99), ("Summit 4P Tent", "Shelter", 289.99),
    ("UltraLight Bivy", "Shelter", 79.99), ("CloudNine Sleeping Bag", "Sleep", 129.99),
    ("Alpine -10C Sleeping Bag", "Sleep", 219.99), ("Foam Sleep Pad", "Sleep", 39.99),
    ("Inflatable Sleep Pad", "Sleep", 89.99), ("60L Trail Backpack", "Packs", 219.99),
    ("35L Daypack", "Packs", 99.99), ("Hydration Vest", "Packs", 74.99),
    ("Titanium Cookset", "Cooking", 64.99), ("Camp Stove", "Cooking", 54.99),
    ("Water Filter Straw", "Cooking", 24.99), ("Collapsible Cookware Set", "Cooking", 49.99),
    ("Trekking Poles (Pair)", "Gear", 59.99), ("Headlamp 400lm", "Gear", 34.99),
    ("Camp Lantern", "Gear", 29.99), ("Multi-Tool", "Gear", 44.99),
    ("Waterproof Rain Shell", "Apparel", 149.99), ("Insulated Jacket", "Apparel", 179.99),
    ("Trail Running Shoes", "Apparel", 129.99), ("Hiking Boots", "Apparel", 169.99),
    ("Merino Wool Base Layer", "Apparel", 69.99), ("Trekking Socks (3-Pack)", "Apparel", 24.99),
    ("Compression Dry Bag Set", "Accessories", 34.99), ("Carabiner 6-Pack", "Accessories", 14.99),
    ("Camp Chair", "Accessories", 79.99), ("Portable Solar Charger", "Accessories", 59.99),
    ("First Aid Kit", "Accessories", 29.99), ("Bear Canister", "Accessories", 74.99),
]
products = pd.DataFrame([
    (f"PROD{100+i}", name, cat, price, round(price * rng.uniform(0.4, 0.55), 2))
    for i, (name, cat, price) in enumerate(PRODUCTS)
], columns=["product_id", "product_name", "category", "unit_price", "cost_price"])
products.to_csv(DATA_DIR / "raw_products.csv", index=False)
print(f"Products: {len(products)} -> raw_products.csv")

# ----------------------------------------------------------------------
# 3. Orders (with the incident day corruption)
# ----------------------------------------------------------------------
CHANNELS = ["Website", "Mobile App", "Marketplace"]
order_records = []
order_counter = 800000

for day in DAYS:
    is_incident = day.date() == INCIDENT_DAY.date()
    n_orders = int(rng.integers(180, 260))
    if is_incident:
        n_orders = int(n_orders * 1.4)   # incident days often also show a volume blip

    for _ in range(n_orders):
        order_id = f"ORD{order_counter}"
        order_counter += 1

        cust_id = rng.choice(customer_ids)
        prod_row = products.iloc[rng.integers(0, len(products))]
        quantity = int(rng.integers(1, 4))
        hour = int(np.clip(rng.normal(14, 4), 0, 23))
        order_ts = day.replace(hour=hour, minute=int(rng.integers(0, 60)))
        discount_pct = float(rng.choice([0, 0, 0, 0.1, 0.15, 0.2], p=[0.55, 0.1, 0.1, 0.1, 0.1, 0.05]))
        channel = rng.choice(CHANNELS, p=[0.6, 0.3, 0.1])
        product_id = prod_row.product_id
        unit_price = prod_row.unit_price

        if is_incident and rng.random() < 0.35:
            # the batch-job bug: corrupt ~35% of this day's rows in one of several ways
            corruption = rng.choice(["null_customer", "orphan_product", "bad_qty", "price_bug", "duplicate"])
            if corruption == "null_customer":
                cust_id = None
            elif corruption == "orphan_product":
                product_id = f"PROD{900 + int(rng.integers(0, 20))}"   # references a product that doesn't exist
            elif corruption == "bad_qty":
                quantity = int(rng.choice([-1, 0, 999]))
            elif corruption == "price_bug":
                unit_price = round(unit_price * rng.choice([0.001, 100]), 2)   # a pricing multiplier bug

        order_records.append((order_id, cust_id, order_ts.strftime("%Y-%m-%d %H:%M:%S"),
                               product_id, quantity, unit_price, discount_pct, channel, is_incident))

        if is_incident and rng.random() < 0.06:
            # duplicate this row outright (simulates a retried batch write)
            order_records.append((order_id, cust_id, order_ts.strftime("%Y-%m-%d %H:%M:%S"),
                                   product_id, quantity, unit_price, discount_pct, channel, is_incident))

orders = pd.DataFrame(order_records, columns=[
    "order_id", "customer_id", "order_timestamp", "product_id", "quantity",
    "unit_price", "discount_pct", "channel", "is_incident_day"
])
orders.to_csv(DATA_DIR / "raw_orders.csv", index=False)
print(f"Orders: {len(orders):,} -> raw_orders.csv "
      f"(incident day {INCIDENT_DAY.date()}: {(orders.is_incident_day).sum():,} rows)")

# ----------------------------------------------------------------------
# 4. Payments
# ----------------------------------------------------------------------
valid_orders = orders.drop_duplicates(subset=["order_id"])
payment_records = []
payment_counter = 500000

for row in valid_orders.itertuples(index=False):
    if rng.random() < 0.05:
        continue   # ~5% of orders: payment not processed yet (normal lag)

    order_value = round(max(row.quantity, 0) * row.unit_price * (1 - row.discount_pct), 2)
    method = rng.choice(["Credit Card", "PayPal", "Apple Pay", "Debit Card"], p=[0.5, 0.25, 0.15, 0.10])
    status = rng.choice(["Captured", "Failed", "Refunded"], p=[0.93, 0.04, 0.03])
    order_dt = datetime.strptime(row.order_timestamp, "%Y-%m-%d %H:%M:%S")
    paid_at = order_dt + timedelta(minutes=int(rng.integers(1, 90)))

    payment_records.append((f"PAY{payment_counter}", row.order_id, order_value, method, status,
                             paid_at.strftime("%Y-%m-%d %H:%M:%S")))
    payment_counter += 1

payments = pd.DataFrame(payment_records, columns=[
    "payment_id", "order_id", "amount", "payment_method", "status", "paid_at"
])
payments.to_csv(DATA_DIR / "raw_payments.csv", index=False)
print(f"Payments: {len(payments):,} -> raw_payments.csv")

print("\nAll 4 raw tables generated.")
