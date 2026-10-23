# churnhouse — Customer 360 Lakehouse

A small data platform for a telecom company that answers one question:
**which customers are likely to churn, and why?**

- **Storage**: MinIO (S3-compatible) + Apache Iceberg tables
- **Query engine**: Trino (Superset reads through it)
- **Ingestion**: dlt (Python) — append-only Bronze
- **Transformation**: dbt — Silver (clean) → Gold (business models)
- **Dashboards**: Superset
- **Orchestration**: Airflow — daily runs, retries, alerts
- **CI**: GitHub Actions runs dbt tests on every PR

3 raw sources (telco customers CSV, generated support tickets, generated payments)
→ Bronze → Silver → Gold, with data quality tests at every layer.

## Architecture

```
3 CSV files
    |
    v
dlt (Python)  copies as-is
    |
BRONZE  raw, append-only
    |  dbt
SILVER  clean, masked, deduped, rejected_rows
    |  dbt
GOLD    customer_360 · customer_risk · monthly_revenue · risk_validation
    |
    +--> Superset (through Trino)
```

## Status

Phases 0–8 under construction.
