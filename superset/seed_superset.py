# One-shot setup: connect Superset to Trino + register the 4 gold datasets.
# Run while both stacks are up:  uv run python superset/seed_superset.py
# Idempotent: an existing database or dataset is re-used, not duplicated.
import json
import sys
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

BASE = "http://localhost:8088"

DB_NAME = "Churn Lakehouse (Trino)"
SQLALCHEMY_URI = "trino://admin@trino:8080/iceberg"

# credentials live in the gitignored .env; nothing password-shaped goes in code
_ENVFILE = Path(__file__).resolve().parent.parent / ".env"


def env(name):
    if _ENVFILE.exists():
        for line in _ENVFILE.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    sys.exit(f"✗ {name} missing in .env (see .env.example for the names)")

GOLD_TABLES = ["customer_360", "customer_risk", "monthly_revenue", "risk_validation"]
SCHEMA = "gold"

opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def call(method, path, body=None, token=None, csrf=None):
    req = urllib.request.Request(BASE + path, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    if csrf:
        req.add_header("X-CSRFToken", csrf)
    data = json.dumps(body).encode() if body is not None else None
    try:
        resp = opener.open(req, data, timeout=60)
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, (json.loads(raw) if raw else {})


def fail(msg):
    print("✗ " + msg)
    sys.exit(1)


def login_as():
    """Bearer token + CSRF token (both needed for writes)."""
    user, password = env("SUPERSET_USER"), env("SUPERSET_PASSWORD")
    code, out = call("POST", "/api/v1/security/login",
                     {"username": user, "password": password,
                      "provider": "db", "refresh": True})
    if code != 200:
        fail(f"login returned {code}: {out}")
    token = out["access_token"]
    code, out = call("GET", "/api/v1/security/csrf_token/", token=token)
    if code != 200:
        fail(f"csrf token returned {code}: {out}")
    return token, out["result"]


def main():
    # 1 + 2. login and CSRF
    token, csrf = login_as()

    # 3. the Trino database (idempotent)
    code, db = call("POST", "/api/v1/database/",
                    {"database_name": DB_NAME,
                     "sqlalchemy_uri": SQLALCHEMY_URI,
                     "configuration_method": "sqlalchemy_form",
                     "expose_in_sqllab": True},
                    token=token, csrf=csrf)
    if code == 201:
        db_id = db["id"]
        print(f"✓ database created: {DB_NAME} (id {db_id})")
    else:
        existing = list_databases(token, csrf)
        matches = [(d["id"], d["database_name"]) for d in existing
                   if d["database_name"] == DB_NAME]
        if matches:
            db_id = matches[0][0]
            print(f"✓ database already exists: {DB_NAME} (id {db_id})")
        else:
            fail(f"database creation returned {code}: {db}")

    # 4. sanity check: does Superset truly reach Trino?
    code, out = call("POST", "/api/v1/database/test_connection/",
                     {"sqlalchemy_uri": SQLALCHEMY_URI,
                      "configuration_method": "sqlalchemy_form",
                      "database_name": DB_NAME},
                     token=token, csrf=csrf)
    if code != 200:
        fail(f"connection test returned {code}: {out}")
    print("✓ connection test: superset -> trino spoken")

    # 5. register gold datasets (skip ones that already exist)
    datasets = list_datasets(token, csrf)
    have = {(d["schema"], d["table_name"]) for d in datasets}
    for table in GOLD_TABLES:
        if (SCHEMA, table) in have:
            print(f"  (already registered: {SCHEMA}.{table})")
            continue
        code, out = call("POST", "/api/v1/dataset/",
                         {"database": db_id, "table_name": table, "schema": SCHEMA},
                         token=token, csrf=csrf)
        if code == 201:
            print(f"✓ dataset registered: gold.{table}")
        else:
            fail(f"dataset {table} returned {code}: {out}")

    # 6. final receipt (column metadata lives on the detail endpoint only)
    datasets = [d for d in list_datasets(token, csrf) if d["schema"] == SCHEMA]
    print()
    print(f"Gold datasets in Superset ({len(datasets)}):")
    for d in sorted(datasets, key=lambda x: x["table_name"]):
        code, det = call("GET", f"/api/v1/dataset/{d['id']}", token=token, csrf=csrf)
        n_cols = len(det["result"].get("columns") or [])
        print(f"  gold.{d['table_name']:<18} ({n_cols} columns)")


def list_databases(token, csrf):
    code, out = call("GET", "/api/v1/database/?page_size=100", token=token, csrf=csrf)
    if code != 200:
        fail(f"list databases returned {code}: {out}")
    return out["result"]


def list_datasets(token, csrf):
    code, out = call("GET", "/api/v1/dataset/?page_size=100", token=token, csrf=csrf)
    if code != 200:
        fail(f"list datasets returned {code}: {out}")
    return out["result"]


if __name__ == "__main__":
    main()
