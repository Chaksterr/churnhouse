#!/usr/bin/env bash
# churnhouse ops room: scheduler + dag-processor + triggerer + UI, one process.
#
#   docker compose up -d        # lakehouse underneath must be up
#   ./orchestration/run.sh      # UI http://localhost:8081 (trino owns 8080)
#   login admin / see orchestration/simple_auth_manager_passwords.json.generated
#   first boot ~30 s; stop with Ctrl-C

set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/.."   # repo root, so tasks run next to dbt/

export AIRFLOW_HOME="$PWD/orchestration"                       # metadata db + logs live here
export AIRFLOW__CORE__DAGS_FOLDER="$AIRFLOW_HOME/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES="False"                    # no demo dags in our ops room
export AIRFLOW__WEBSERVER__WEB_SERVER_PORT="8081"              # 8080 = trino

exec uv run airflow standalone
