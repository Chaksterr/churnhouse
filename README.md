# churnhouse

A small data platform for a telecom company that answers:
**which customers are likely to churn, and why?**
The value is in the *pipeline*, not in a dashboard project.

## Architecture (simple)

```
3 CSVs (CRM · support · billing)
      │
      ▼
   loader ──►  BRONZE (raw, append-only)  ──  MinIO + Iceberg + Trino
      │   dbt
      ▼
   SILVER (clean, masked, tested) ── bad rows → rejected_rows
      │   dbt
      ▼
   GOLD  (customer_360 · risk score + reasons · validation)
      │
      ▼
   Superset dashboards          Airflow runs it daily + alerts
```

**Everything is Iceberg tables on MinIO, read through Trino.**
Airflow orchestrates nightly. GitHub Actions tests every PR.

## Tools used

| Tool | One job |
|---|---|
| **MinIO** | the disk (S3-compatible object storage) |
| **Iceberg** | tables with snapshots / time travel on files |
| **REST catalog** | the shared registry of tables |
| **Trino** | the SQL engine (loader, dbt, Superset all query through it) |
| **trino python client** | the loader: chunked append-only loads + audit columns |
| **dbt** | SQL transforms + tests in version control |
| **Superset** | dashboards |
| **Airflow** | orchestration + retries + freshness SLA |
| **uv** | reproducible Python installs (lockfile-committed) |

## Quickstart

```bash
cp .env.example .env && docker compose up -d    # lakehouse
# console http://localhost:9001 → create bucket "warehouse"
uv sync
uv run python generator/generate.py             # deterministic synthetic data
```

Under construction: ingestion → dbt layers → dashboard → orchestration.

## Repo map

```
├── docker-compose.yml      # minio + iceberg catalog + trino
├── generator/generate.py   # synthetic sources (seeded)
├── ingestion/              # loader → bronze (append-only)
├── dbt/                    # silver + gold models + tests
└── orchestration/          # airflow dags + CI
```
