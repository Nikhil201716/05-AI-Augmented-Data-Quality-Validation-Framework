"""
load_raw_to_duckdb.py
----------------------
The "EL" half of ELT: loads the 4 raw CSVs into DuckDB as raw_* tables,
untouched. dbt then owns the "T" half - all cleaning and transformation
happens inside dbt models, not here. This mirrors how real data
platforms are actually built: an extraction/loading tool (Fivetran,
Airbyte, or a custom script) lands raw data in the warehouse, and dbt
is only ever responsible for transforming what's already there.
"""

import duckdb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DB_PATH = ROOT / "database" / "warehouse.duckdb"
DB_PATH.parent.mkdir(exist_ok=True)

conn = duckdb.connect(str(DB_PATH))

tables = ["raw_customers", "raw_products", "raw_orders", "raw_payments"]
for t in tables:
    csv_path = DATA_DIR / f"{t}.csv"
    conn.execute(f"CREATE OR REPLACE TABLE {t} AS SELECT * FROM read_csv_auto('{csv_path.as_posix()}')")
    count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    print(f"Loaded {t}: {count:,} rows")

conn.close()
print(f"\nRaw tables loaded into {DB_PATH}")
