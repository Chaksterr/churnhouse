# churnhouse

A small telecom data platform that answers one question:
**which customers are likely to churn, and why?**
Three CSVs go in; a tested iceberg lakehouse comes out; Superset shows the
result and Airflow keeps it fresh every night. The value is the *pipeline*,
not the dashboard.

## Architecture

```
3 CSVs (CRM · support · billing)
      │
      ▼
   loader ──► BRONZE (raw, append-only) ── MinIO + Iceberg + Trino
      │  dbt
      ▼
   SILVER (clean, masked, tested) ── bad rows → rejected_rows
      │  dbt
      ▼
   GOLD (customer_360 · risk score + reasons · validation)
      │
      ├──► Superset dashboard            :8088
      └──► Airflow daily at 02:00        :8081   (ingest → silver → gold → freshness check)
```

Everything is Iceberg tables on MinIO, queried through Trino.
GitHub Actions runs dbt parse + a full dbt build on every PR.

## Tools (one job each)

| Tool | Job |
|---|---|
| MinIO | the disk (S3 API) |
| Iceberg REST catalog + postgres | the table registry (MVCC-safe) |
| Trino | the SQL engine everything reads through |
| dbt | SQL transforms + tests |
| Superset | the dashboard |
| Airflow | nightly runs, retries, 24h freshness guard |
| uv | reproducible Python (lockfile committed) |

## Run it

```bash
cp .env.example .env          # then fill in real values
uv sync

docker compose up -d          # minio + catalog + trino + superset
# one-time by hand: create bucket "warehouse" at http://localhost:9001

uv run python generator/generate.py
uv run python ingestion/load_bronze.py    # rerun appends rows — dedup is silver's job
uv run dbt build --project-dir dbt --profiles-dir dbt

# BI layer — first boot only, then the two scripts any time
docker exec superset superset db upgrade
docker exec superset superset init
docker exec superset flask fab create-admin --username admin \
  --password <SUPERSET_PASSWORD from .env> --firstname Churn --lastname House \
  --email admin@churnhouse.local
uv run python superset/seed_superset.py     # register the 4 gold datasets
uv run python superset/build_dashboard.py   # build the dashboard, gate-checked vs trino

./orchestration/run.sh        # airflow (one process; password file it prints; Ctrl-C stops)
```

## Where things live

| Path | Job |
|---|---|
| `generator/` | deterministic synthetic data (seeded) |
| `ingestion/` | loader: CSV → bronze, chunked inserts + audit columns |
| `dbt/` | silver + gold models, schema tests, 3 SQL data tests |
| `superset/` | image + the two API scripts (seed datasets, build dashboard) |
| `orchestration/` | the daily Airflow DAG (`dags/churnhouse_daily.py`) + `run.sh` |
| `.github/workflows/` | CI: dbt parse, then dbt build on a throwaway lakehouse |
| `setup_infra.sql` | re-creates the 3 schemas if the catalog registry is ever wiped |

## Ports

| Port | Service |
|---|---|
| 8080 | Trino (SQL + UI) |
| 8081 | Airflow UI |
| 8088 | Superset |
| 9000 / 9001 | MinIO API / console |
| 8181 | Iceberg REST catalog |

## Good to know

- **Scripts own the dashboard.** Re-running `build_dashboard.py` overwrites
  chart/layout/banner edits made by hand — the pipeline is the source of truth.
- **Numbers move.** Gold churn stats change slightly after a pipeline rerun
  (append-only ingest + dedup-in-silver). That is the system working, not a bug.
- **Freshness guard**: if any gold table has not been written for >24h, the
  Airflow run fails on a `$snapshots` timestamp check — no fake "last built" tables.
