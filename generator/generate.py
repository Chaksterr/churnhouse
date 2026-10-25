"""churnhouse data forge.
Generates support_tickets (5,000), payments (30,000) and customers_contact (7,043).
Fixed seed -> byte-identical files on every run.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

SEED = 42
RAW_FILE = Path("data/raw/telco_customers.csv")
OUT_DIR = Path("data/generated")

N_TICKETS = 5_000
N_PAYMENTS = 30_000

TICKET_CATEGORIES = [
    "billing_dispute", "technical_issue", "network_quality",
    "service_change", "general_inquiry",
]
TICKET_STATUSES = ["open", "resolved", "closed"]

TICKETS_WINDOW_DAYS = 90
PAYMENTS_WINDOW_DAYS = 365

rng = random.Random(SEED)
fake = Faker("en_US")
fake.seed_instance(SEED)


def load_customers() -> list[dict]:
    rows = []
    with RAW_FILE.open(newline="") as f:
        for r in csv.DictReader(f):
            rows.append({
                "id": r["customerID"],
                "contract": r["Contract"],
                "monthly": float(r["MonthlyCharges"]),
                "method": r["PaymentMethod"],
                "churned": r["Churn"] == "Yes",
            })
    return rows


def build_tickets(customers: list[dict]) -> list[list]:
    pool: list[int] = []
    for i, c in enumerate(customers):
        lam = 0.55 + (1.0 if c["churned"] else 0.0)
        pool.extend([i] * (1 + int(rng.random() * lam)))
    if len(pool) < N_TICKETS:
        raise SystemExit(f"ticket pool too small ({len(pool)})")

    chosen = rng.sample(pool, N_TICKETS)
    today = datetime.now().date()

    rows = []
    for n, idx in enumerate(chosen, start=1):
        c = customers[idx]
        created = today - timedelta(days=rng.randrange(TICKETS_WINDOW_DAYS),
                                    hours=rng.randrange(0, 24),
                                    minutes=rng.randrange(0, 60))
        weights = (0.30, 0.25, 0.20, 0.15, 0.10) if c["churned"] else \
                  (0.06, 0.10, 0.16, 0.32, 0.36)
        rows.append([
            f"TKT-{n:06d}", c["id"],
            rng.choice(TICKET_CATEGORIES),
            rng.choice(TICKET_STATUSES),
            created.isoformat(),
            rng.choices(range(1, 6), weights=weights)[0],
        ])
    rows.sort(key=lambda r: r[4])
    return rows


def build_payments(customers: list[dict]) -> list[list]:
    pool: list[int] = []
    for i, c in enumerate(customers):
        pool.extend([i] * (3 + int(rng.random() * 6)))
    chosen = rng.sample(pool, N_PAYMENTS)
    today = datetime.now().date()

    rows = []
    for n, idx in enumerate(chosen, start=1):
        c = customers[idx]
        pay_date = today - timedelta(days=rng.randrange(PAYMENTS_WINDOW_DAYS))
        amount = round(c["monthly"] * rng.uniform(0.95, 1.05), 2)
        p_failed = 0.14 if c["churned"] else 0.06
        status = "failed" if rng.random() < p_failed else "succeeded"
        rows.append([
            f"PMT-{n:07d}", c["id"], pay_date.isoformat(),
            amount, c["method"], status,
        ])
    rows.sort(key=lambda r: r[2])
    return rows


def build_contacts(customers: list[dict]) -> list[list]:
    return [[c["id"], fake.name(), fake.email(), fake.phone_number()]
            for c in customers]


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def check_integrity(all_used_ids: set[str], customer_ids: set[str]) -> None:
    orphans = all_used_ids - customer_ids
    if orphans:
        raise SystemExit(f"INTEGRITY FAIL: {len(orphans)} orphan IDs: {list(orphans)[:5]}")
    print(f"✔ integrity: all {len(all_used_ids)} used customer IDs exist in the telco file")


def main() -> None:
    customers = load_customers()
    customer_ids = {c["id"] for c in customers}
    print(f"loaded {len(customer_ids)} real customers from {RAW_FILE}")

    tickets = build_tickets(customers)
    payments = build_payments(customers)
    contacts = build_contacts(customers)

    write_csv(OUT_DIR / "support_tickets.csv",
              ["ticket_id", "customer_id", "category", "status",
               "created_at", "satisfaction_score"], tickets)
    write_csv(OUT_DIR / "payments.csv",
              ["payment_id", "customer_id", "payment_date", "amount",
               "method", "status"], payments)
    write_csv(OUT_DIR / "customers_contact.csv",
              ["customer_id", "full_name", "email", "phone"], contacts)

    used = {r[1] for r in tickets} | {r[1] for r in payments}
    check_integrity(used, customer_ids)

    churners_touched = len(used & {c["id"] for c in customers if c["churned"]})
    print(f"support_tickets.csv : {len(tickets):>6} rows ({churners_touched} churners referenced)")
    print(f"payments.csv        : {len(payments):>6} rows")
    print(f"customers_contact.csv: {len(contacts):>6} rows (PII)")


if __name__ == "__main__":
    main()
