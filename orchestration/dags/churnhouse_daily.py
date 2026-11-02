"""churnhouse daily ops DAG.

    ingest -> dbt silver (+ tests) -> dbt gold (+ tests) -> freshness guard

- each task retries 2x, 2 min apart; a broken step blocks the next one
- freshness: gold tables must have been written within the last 24h,
  checked via iceberg $snapshots committed_at (no fake "last-run" tables)
- kept simple on purpose: no webhooks, no maintenance DAG

Schedule: 02:00 UTC daily; manual trigger from the UI works any time.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import trino.dbapi
from airflow.decorators import dag, task

import trino

REPO = Path(__file__).resolve().parents[2]  # orchestration/dags/*.py -> repo root

# airflow's venv also has dbt - find its binary next to the interpreter
# (no PATH hoping: the scheduler may be started from any shell)
VENV_BIN = Path(sys.executable).resolve().parent
DBT_BIN = str(VENV_BIN / "dbt") if (VENV_BIN / "dbt").exists() else "dbt"

# dbt 1.x click CLI: every flag belongs AFTER the subcommand
DBT = [DBT_BIN, "--no-use-colors"]

GOLD_TABLES = ["customer_360", "customer_risk", "monthly_revenue", "risk_validation"]
FRESH_WINDOW_HOURS = 24  # gold older than this => freshness task fails (plan rule)

DEFAULT_ARGS = {"retries": 2, "retry_delay": timedelta(minutes=2)}


def _run(cmd: list[str]) -> str:
    """Run a command at repo root; print the tail to task logs; raise on failure."""
    proc = subprocess.run(cmd, cwd=REPO, text=True, capture_output=True)
    print(proc.stdout[-6000:])
    if proc.stderr:
        print(proc.stderr[-2000:])
    if proc.returncode != 0:
        raise RuntimeError(f"exit {proc.returncode} running: {' '.join(cmd)}")
    return (proc.stdout or "").strip()


# --- the pipeline -----------------------------------------------------------
@task(**DEFAULT_ARGS)  # type: ignore[arg-type]
def ingest() -> str:
    """CSV -> iceberg.bronze (append-only; dedup is silver's job)."""
    return _run([sys.executable, "ingestion/load_bronze.py"])


@task(**DEFAULT_ARGS)  # type: ignore[arg-type]
def dbt_build_silver() -> str:
    """Silver models + the tests attached to them (fail between layers, not after)."""
    return _run([*DBT, "build", "--project-dir", "dbt", "--profiles-dir", "dbt",
                 "--select", "path:models/silver"])


@task(**DEFAULT_ARGS)  # type: ignore[arg-type]
def dbt_build_gold() -> str:
    """Gold models + their tests (incl. the high-band-churns-more guard)."""
    return _run([*DBT, "build", "--project-dir", "dbt", "--profiles-dir", "dbt",
                 "--select", "path:models/gold"])


@task  # no retries: a stale warehouse stays stale however often we look
def freshness_gold() -> str:
    """Fail when any gold table was last written more than FRESH_WINDOW_HOURS ago."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=FRESH_WINDOW_HOURS)
    conn = trino.dbapi.connect(host="localhost", port=8080, user="admin", catalog="iceberg")
    stale: list[str] = []
    try:
        cur = conn.cursor()
        for table in GOLD_TABLES:
            # trino parses `$` only inside ONE quoted identifier
            cur.execute(f'SELECT max(committed_at) FROM iceberg.gold."{table}$snapshots"')
            (latest,) = cur.fetchone()
            if hasattr(latest, "tzinfo") and latest.tzinfo is None:
                latest = latest.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - latest).total_seconds() / 3600 if latest else None
            status = "STALE" if age is None or latest < cutoff else "fresh"
            print(f"  {table:<18} last write: {latest}  ({status})")
            if age is None:
                stale.append(f"{table} has no snapshots at all")
            elif latest < cutoff:
                stale.append(f"{table} last written {age:.1f}h ago (limit {FRESH_WINDOW_HOURS}h)")
    finally:
        conn.close()
    if stale:
        raise RuntimeError("gold data is stale: " + "; ".join(stale))
    return f"all {len(GOLD_TABLES)} gold tables fresh (<{FRESH_WINDOW_HOURS}h)"


@dag(
    dag_id="churnhouse_daily",
    schedule="0 2 * * *",  # 02:00 UTC every day, per plan
    start_date=datetime(2026, 10, 29, tzinfo=timezone.utc),  # the day the stack froze
    catchup=False,
    tags=["churnhouse"],
    doc_md=__doc__,
)
def churnhouse_daily() -> None:
    ingest() >> dbt_build_silver() >> dbt_build_gold() >> freshness_gold()


churnhouse_daily()
