"""churnhouse bronze loader.

Loads the 4 source CSVs into iceberg.bronze (trino), chunked multi-row INSERTs.
Append-only: every run adds its rows again — dedup is Silver's job (dbt).
Every row gets two audit columns: ingested_at, source_file.

Why not dlt: dlt 1.31 has no trino destination; its generic sqlalchemy path
inserts row-by-row (~10 rows/s). Direct chunked inserts are ~200x faster.
"""

from __future__ import annotations

import csv
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import trino.dbapi

import trino

CHUNK = 2000  # rows per INSERT statement

# columns in source order; audit columns are appended by the loader
SCHEMAS = {
    "customers": [
        "customer_id", "gender", "senior_citizen", "partner", "dependents",
        "phone_service", "multiple_lines", "internet_service", "online_security",
        "online_backup", "device_protection", "tech_support", "streaming_tv",
        "streaming_movies", "contract", "paperless_billing", "payment_method",
        "tenure", "monthly_charges", "total_charges", "churn",
    ],
    "support_tickets": [
        "ticket_id", "customer_id", "category", "status",
        "created_at", "satisfaction_score",
    ],
    "payments": [
        "payment_id", "customer_id", "payment_date", "amount", "method", "status",
    ],
    "customers_contact": ["customer_id", "full_name", "email", "phone"],
}

# numeric columns: int -> bigint, float -> double; everything else is varchar
NUMERIC = {
    "customers": {"senior_citizen": "bigint", "tenure": "bigint",
                  "monthly_charges": "double", "total_charges": "double"},
    "support_tickets": {"satisfaction_score": "bigint"},
    "payments": {"amount": "double"},
    "customers_contact": {},
}

CSV_FILES = {
    "customers": "data/raw/telco_customers.csv",
    "support_tickets": "data/generated/support_tickets.csv",
    "payments": "data/generated/payments.csv",
    "customers_contact": "data/generated/customers_contact.csv",
}


def snake(name: str) -> str:
    """customerID -> customer_id, MonthlyCharges -> monthly_charges."""
    s = re.sub("(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub("([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def col_type(table: str, col: str) -> str:
    return NUMERIC[table].get(col, "varchar")


def fmt(value, trino_type: str) -> str:
    """One literal for the VALUES clause; empty -> NULL."""
    if value is None or value == "":
        return "NULL"
    if trino_type == "bigint":
        return str(int(value))
    if trino_type == "double":
        return str(float(value))
    return "'" + value.replace("'", "''") + "'"


def read_rows(path: Path, table: str, ingested_at: str):
    """CSV lines as dict: snake_case keys, typed values, + audit columns."""
    types = NUMERIC[table]
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        header_map = {h: snake(h) for h in (reader.fieldnames or [])}
        for row in reader:
            out = {}
            for h, v in row.items():
                v = (v or "").strip()
                if not v:
                    out[header_map[h]] = None
                elif types.get(header_map[h]) == "bigint":
                    out[header_map[h]] = int(v)
                elif types.get(header_map[h]) == "double":
                    out[header_map[h]] = float(v)
                else:
                    out[header_map[h]] = v
            out["ingested_at"] = ingested_at
            out["source_file"] = path.name
            yield out


def create_table(cur, table: str, ingested_at_type: str) -> None:
    cols = [f"{c} {col_type(table, c)}" for c in SCHEMAS[table]]
    cols.append(f"ingested_at {ingested_at_type}")
    cols.append("source_file varchar")
    sql = f"CREATE TABLE IF NOT EXISTS bronze.{table} ({', '.join(cols)})"
    cur.execute(sql)
    cur.fetchall()  # trino reports DDL errors on fetch - without it a failed create passes silently


def load_table(cur, table: str, path: Path, ingested_at: str) -> int:
    create_table(cur, table, "varchar")
    prefix_cols = [*SCHEMAS[table], "ingested_at", "source_file"]
    cols_sql = ", ".join(prefix_cols)
    done = 0
    batch: list[dict] = []
    for row in read_rows(path, table, ingested_at):
        batch.append(row)
        if len(batch) >= CHUNK:
            done += insert_batch(cur, table, cols_sql, batch)
            batch = []
    if batch:
        done += insert_batch(cur, table, cols_sql, batch)
    return done


def insert_batch(cur, table: str, cols_sql: str, batch: list[dict]) -> int:
    rows = ", ".join(
        "(" + ", ".join(fmt(r[c], col_type(table, c)) for c in SCHEMAS[table])
        + ", '%s', '%s')" % (r["ingested_at"], r["source_file"])
        for r in batch
    )
    sql = (f"INSERT INTO bronze.{table} SELECT * FROM "
           f"(VALUES {rows}) AS t({cols_sql})")
    cur.execute(sql)
    cur.fetchall()
    return len(batch)


def connect():
    conn = trino.dbapi.connect(host="localhost", port=8080, user="admin",
                               catalog="iceberg", schema="bronze")
    cur = conn.cursor()
    cur.execute("CREATE SCHEMA IF NOT EXISTS bronze")  # fresh lakehouse: no manual setup
    cur.fetchall()
    return cur


def main() -> None:
    cur = connect()

    if "--schema-only" in sys.argv:
        # CI mode: create the 4 empty bronze tables, load nothing.
        # (data/ CSVs don't exist on a runner; dbt build can still run + test)
        for table in SCHEMAS:
            create_table(cur, table, "varchar")
        print(f"schema-only: bronze ready ({len(SCHEMAS)} empty tables, no rows loaded)")
        return

    ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"run stamp: {ingested_at}")
    t0 = time.perf_counter()

    total = 0
    for table, file in CSV_FILES.items():
        n = load_table(cur, table, Path(file), ingested_at)
        total += n
        print(f"  {table:<20} {n:>7} rows appended")

    print(f"total: {total} rows in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
