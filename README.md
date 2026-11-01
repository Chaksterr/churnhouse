# 🏠 churnhouse

**An end-to-end data lakehouse that predicts which telecom customers will churn, and explains why.**

![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)
![dbt](https://img.shields.io/badge/dbt-Trino-FF694B?logo=dbt&logoColor=white)
![Trino](https://img.shields.io/badge/Trino-470-DD00A1?logo=trino&logoColor=white)
![Iceberg](https://img.shields.io/badge/Apache%20Iceberg-REST-4E8EE9)
![Airflow](https://img.shields.io/badge/Airflow-3-017CEE?logo=apacheairflow&logoColor=white)
![Superset](https://img.shields.io/badge/Superset-6.1-20A6C9)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![CI](https://img.shields.io/badge/CI-GitHub%20Actions-2088FF?logo=githubactions&logoColor=white)

Four CSVs go in. Out comes a **tested, versioned Iceberg lakehouse**, a
**Superset dashboard**, and an **Airflow pipeline** that refreshes everything
nightly. It runs locally with Docker and needs no cloud account.

---

## ✨ Highlights

- 🥉🥈🥇 **Medallion architecture** (bronze → silver → gold) on Apache Iceberg + MinIO
- 🧪 **35 automated dbt tests**, including a business-rule test that fails the build if the risk model stops predicting churn
- 🔒 **PII masking** in silver (emails, phones), enforced by tests
- 🗂️ **Quarantine table**: rejected rows are kept with a reason instead of silently dropped
- ⏰ **Airflow orchestration**: daily schedule, retries, and a 24h freshness guard based on Iceberg snapshots
- 🤖 **CI/CD**: every PR spins up a throwaway lakehouse in GitHub Actions and runs the full dbt build
- 📊 **Dashboard as code**: Superset charts are built by script and cross-checked against Trino
- ♻️ **Reproducible**: seeded data generator and a locked Python environment (`uv.lock`)

---

## 🏗️ Architecture

```
telco_customers.csv (real)  +  tickets · payments · contacts (generated)
      │  ingestion/load_bronze.py
      ▼
🥉 BRONZE  raw, append-only, + ingested_at / source_file
      │  dbt
      ▼
🥈 SILVER  deduped, typed, PII masked ── superseded rows → rejected_rows
      │  dbt
      ▼
🥇 GOLD    customer_360 · customer_risk · monthly_revenue · risk_validation
      │
      ├──► 📊 Superset dashboard "Churn House"   :8088
      └──► ⏰ Airflow, daily 02:00 UTC           :8081
             ingest → silver (+tests) → gold (+tests) → freshness check
```

| Tool | Role |
|---|---|
| 🪣 MinIO | S3-compatible object storage |
| 🧊 Iceberg REST catalog + Postgres | table format + registry |
| ⚡ Trino | the single SQL engine for loader, dbt and BI |
| 🔧 dbt | silver/gold transforms + tests |
| 📊 Superset | dashboard |
| ⏰ Airflow | scheduling, retries, freshness monitoring |
| 📦 uv | Python dependency management |

---

## 🎯 How churn risk is scored

`customer_risk` adds up five transparent SQL rules (0–8 points) and writes a
readable `reasons` column, e.g. *"month-to-month contract + 2 tickets in 90d"*.
Every score can be explained to a business user.

| Rule | Points |
|---|---|
| Month-to-month contract | +2 |
| Tenure under 6 months | +2 |
| Failed payment in last 90 days | +2 |
| 2+ support tickets in last 90 days | +1 |
| Average satisfaction under 3 | +1 |

**Bands:** 🔴 high ≥ 5 · 🟠 medium 3–4 · 🟢 low 0–2

✅ **Validated against real outcomes:** `risk_validation` shows churn % rising
from low → medium → high, and a dbt test breaks the build if that ever stops being true.

---

## 🛡️ Data quality & reliability

| Safeguard | What it does |
|---|---|
| 🧪 dbt tests (35) | schema tests + custom SQL tests for masking and model validity |
| 🗂️ `silver.rejected_rows` | logs every duplicate silver drops, with a reason |
| ⏱️ Freshness guard | Airflow fails if any gold table's latest Iceberg `$snapshots` commit is older than 24h |
| 🔁 Retries | each pipeline task retries twice, and a failed step blocks downstream steps |
| 🤖 CI | `dbt parse` → full `dbt build` on an empty lakehouse, on every PR and push to `main` |

---

## 🚀 Quick start

**Prerequisites:** Docker + Compose, [uv](https://docs.astral.sh/uv/), Python 3.13,
and the IBM *Telco Customer Churn* dataset (7,043 rows) saved as
`data/raw/telco_customers.csv`. `data/` is gitignored, so you need to supply this file yourself.

```bash
# 1️⃣ config + dependencies
cp .env.example .env                 # fill in real values
uv sync

# 2️⃣ infrastructure
docker compose up -d                 # minio, catalog, trino, superset
# one time: create bucket "warehouse" at http://localhost:9001

# 3️⃣ data pipeline
uv run python generator/generate.py
uv run python ingestion/load_bronze.py
uv run dbt build --project-dir dbt --profiles-dir dbt

# 4️⃣ dashboard (the three superset commands are first boot only)
docker exec superset superset db upgrade
docker exec superset superset init
docker exec superset flask fab create-admin --username admin \
  --password <SUPERSET_PASSWORD> --firstname Churn --lastname House \
  --email admin@churnhouse.local
uv run python superset/seed_superset.py
uv run python superset/build_dashboard.py

# 5️⃣ orchestration
./orchestration/run.sh               # Airflow UI :8081, Ctrl-C to stop
# login: admin / password in orchestration/simple_auth_manager_passwords.json.generated
```

💡 If the catalog registry is ever wiped, run `setup_infra.sql` in Trino to recreate the schemas.

| Port | Service |
|---|---|
| 8080 | Trino |
| 8081 | Airflow |
| 8088 | Superset |
| 9000 / 9001 | MinIO API / console |
| 8181 | Iceberg REST catalog |

---

## 📁 Project structure

```
churnhouse/
├── generator/          # seeded synthetic tickets, payments, contacts
├── ingestion/          # CSV → bronze loader (chunked inserts, audit columns)
├── dbt/
│   ├── models/silver/  # cleaning, dedup, masking, rejected_rows
│   ├── models/gold/    # the 4 business tables
│   └── tests/          # custom SQL data tests
├── superset/           # image + dashboard-as-code scripts
├── orchestration/      # Airflow DAG + run.sh
├── trino/catalog/      # Trino → Iceberg config
└── .github/workflows/  # CI pipeline
```

---

## 🧠 Engineering decisions

- **Postgres over SQLite for the catalog**: SQLite threw `SQLITE_BUSY` when dbt committed tables in parallel. Postgres handles concurrent writes without that lock.
- **Custom loader instead of dlt**: dlt has no Trino destination, and its generic path inserted about 10 rows/s. Chunked multi-row inserts are about 200× faster.
- **Aggregate first, join second**: in `customer_360`, events are aggregated before joining, so a customer with many tickets or payments doesn't get duplicated rows.
- **Rule-based score instead of a black-box model**: every prediction comes with its reasons, and it's validated against real churn.
- **Freshness from Iceberg metadata**: the guard reads real snapshot timestamps instead of a hand-maintained "last run" table.

---

## 📝 Good to know

- Scripts own the dashboard: re-running `build_dashboard.py` overwrites manual edits.
- Numbers drift slightly after reruns (append-only ingest + dedup in silver). This is expected.

---

## 👤 Author

**Ahmad Chakcha**, final-year Data Engineering student.
Feedback and questions are welcome. Feel free to open an issue.
