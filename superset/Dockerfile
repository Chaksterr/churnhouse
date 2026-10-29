# Lean Superset (no drivers) + the one driver the lakehouse needs: trino via sqlalchemy.
FROM apache/superset:6.1.0-lean

USER root
RUN . /app/.venv/bin/activate && uv pip install sqlalchemy-trino

USER superset
