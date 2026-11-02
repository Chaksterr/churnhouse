# churnhouse — one-word commands for the whole lifecycle.
# `make help` lists them. Everything runs from the repo root.

-include .env
export

DBT := uv run dbt --no-use-colors
DBT_ARGS := --project-dir dbt --profiles-dir dbt

.DEFAULT_GOAL := help
.PHONY: help setup up down nuke data ingest transform pipeline docs \
        superset-init dashboard airflow lint check

help: ## list the available commands
	@grep -E '^[a-z-]+:.*## ' $(firstword $(MAKEFILE_LIST)) | awk -F':.*## ' '{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup
setup: ## create .env from the template + install python deps
	@test -f .env || (cp .env.example .env && echo "created .env, edit the passwords")
	uv sync

up: ## start minio, iceberg catalog, trino and superset (waits until healthy)
	docker compose up -d --wait

down: ## stop the stack (data volumes are kept)
	docker compose down

nuke: ## stop the stack AND delete every volume (fresh lakehouse)
	docker compose down -v

# ---------------------------------------------------------------- pipeline
data: ## generate the synthetic tickets / payments / contacts CSVs
	uv run python generator/generate.py

ingest: ## load the 4 CSVs into iceberg.bronze
	uv run python ingestion/load_bronze.py

transform: ## dbt build: silver + gold models and all tests
	$(DBT) build $(DBT_ARGS)

pipeline: data ingest transform ## data -> bronze -> silver -> gold, end to end

docs: ## generate and serve the dbt docs site (lineage graph) on :8000
	$(DBT) docs generate $(DBT_ARGS) && $(DBT) docs serve $(DBT_ARGS) --port 8000

# ---------------------------------------------------------------- serving
superset-init: ## first boot only: migrate superset db + create the admin user
	docker exec superset superset db upgrade
	docker exec superset superset init
	docker exec superset flask fab create-admin --username $(SUPERSET_USER) \
	  --password $(SUPERSET_PASSWORD) --firstname Churn --lastname House \
	  --email admin@churnhouse.local

dashboard: ## register gold datasets + build the dashboard (idempotent)
	uv run python superset/seed_superset.py
	uv run python superset/build_dashboard.py

airflow: ## run airflow standalone, UI on :8081 (Ctrl-C to stop)
	./orchestration/run.sh

# ---------------------------------------------------------------- quality
lint: ## ruff on the python code + dbt parse
	uvx ruff check .
	$(DBT) parse $(DBT_ARGS)

check: ## what CI runs: empty bronze tables + full dbt build (needs `make up`)
	uv run python ingestion/load_bronze.py --schema-only
	$(DBT) build $(DBT_ARGS)
