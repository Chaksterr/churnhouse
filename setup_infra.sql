-- churnhouse infra setup — run after a FRESH catalog (or after wiping the registry).
-- The bucket `warehouse` itself is created by hand in the MinIO console (:9001).
-- Idempotent: safe to run again.

-- the three medallion layers
CREATE SCHEMA IF NOT EXISTS iceberg.bronze;   -- raw, append-only (loader writes here)
CREATE SCHEMA IF NOT EXISTS iceberg.silver;   -- clean + masked (dbt writes here)
CREATE SCHEMA IF NOT EXISTS iceberg.gold;     -- products: dashboards read these (dbt writes here)
