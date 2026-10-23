# churnhouse — Phase Plan & Checklist

Use this file as your working log: **tick `[ ]` → `[x]` as you go. One phase at a time. Every phase ends with a commit and a "Done when" you can prove.**

Target: full platform in **~1 week** (~30 focused hours) — one or two phases per day.

**Ground rule:** folders are created *inside the phase that needs them* (first checklist item of each phase). No pre-building the whole tree.

**Python rule:** we use **uv** only — no raw pip/`python -m venv`. One project at the repo root: `pyproject.toml` declares dependencies, `uv.lock` pins them (both committed), one shared `.venv/` for generator + dlt + dbt. Any "install X" step below means `uv add X`.

| Day | Phase(s) | Name |
|---|---|---|
| 1 | 0 + 1 | Blueprint → Bedrock |
| 2 | 2 + 3 | Data Forge → Ingestion |
| 3 | 4 (part 1) | Refinery: models |
| 4 | 4 (part 2) + 5 | Refinery: tests → Goldsmith |
| 5 | 6 | Showcase |
| 6 | 7 | Ops Room |
| 7 | 8 | Launch |

---

## Phase 0 — 🧭 Blueprint (repo + raw data)

- [x] Repo root ready — only `data/raw/` created (for the dataset); every other folder comes later, inside the phase that needs it
- [x] `git init` on branch `main`
- [x] `.gitignore` covers .env, data/, target/, .venv/, *.duckdb
- [x] `.env` (real values, local only) + `.env.example` (fake values, committed)
- [x] README stub
- [x] Dataset downloaded → `data/raw/telco_customers.csv` (7044 lines ✓)
- [x] Row check: `wc -l` ≈ 7044
- [x] Sanity: `.env` and `data/` both ignored (verified with `git check-ignore`)

**Done when:** ~7044 rows downloaded + `.env`/`data/` actually ignored by git.

**Commit:** `chore: blueprint — structure, env, dataset`

---

## Phase 1 — 🪨 Bedrock (lakehouse core: MinIO + Iceberg + Trino)

- [x] Create folders: `mkdir -p trino/catalog docs/screenshots`
- [x] `docker-compose.yml` at repo root with 4 services: minio, minio-init, iceberg-catalog, trino
- [x] `trino/catalog/iceberg.properties` written (REST catalog → iceberg-catalog:8181, native S3 → minio:9000, lab min-retention = 0s)
- [ ] `docker compose up -d` — all containers healthy
- [ ] Schemas created in Trino: `iceberg.bronze`, `iceberg.silver`, `iceberg.gold`
- [ ] Smoke test: create `bronze.smoke_test`, INSERT 1 row, SELECT returns it
- [ ] **Exercise — change:** run UPDATE then DELETE on smoke_test; after each write, query snapshots/files tables & record row/code changes
- [ ] **Exercise — break (once):** delete one `metadata.json` in MinIO, query the table, write down the failure
- [ ] **Exercise — draw:** sketch the 4 levels (metadata.json → manifest list → manifests → Parquet) from memory
- [ ] 3 screenshots in `docs/screenshots/`
- [ ] Commit

**Done when:** SELECT works + you can explain the 4 Iceberg levels without notes.

**Commit:** `feat: bedrock — minio, iceberg rest catalog, trino`

---

## Phase 2 — 🛠 Data Forge (synthetic sources)

- [ ] Create folder: `mkdir generator`
- [ ] uv project at repo root: `uv init` + `uv add faker` (pyproject.toml + uv.lock + .venv/)
- [ ] `generator/generate.py` with fixed seed (reproducible)
- [ ] `support_tickets.csv` ~5,000 rows, linked to real customer IDs from the Telco file
- [ ] `payments.csv` ~30,000 rows, linked to real customer IDs
- [ ] Guardrail: script fails loudly if an ID is not in the Telco file
- [ ] Optional: `customers_contact.csv` (name, email, phone) to practice masking
- [ ] Both files in `data/generated/`

**Done when:** 2 CSVs generated + every ID exists in the Telco file.

**Commit:** `feat: data forge — tickets + payments generators`

---

## Phase 3 — 🚚 Ingestion (dlt → Bronze)

- [ ] Create folder: `mkdir ingestion`
- [ ] dlt + Trino support: `uv add "dlt[trino]"`
- [ ] `ingestion/load_bronze.py` loads the 3 CSVs into `iceberg.bronze.*`
- [ ] Audit columns on every row: `ingested_at`, `source_file`
- [ ] Append-only mode (old rows never rewritten)
- [ ] Run it twice → second run only adds rows (count check from Trino)
- [ ] Note the ingestion runtimes (baseline for Phase 7)

**Done when:** Trino shows 3 Bronze tables with the right counts + reruns add only new rows.

**Commit:** `feat: ingestion — dlt bronze loader (append-only)`

---

## Phase 4 — 🧪 Refinery (dbt Silver: clean, mask, quarantine)

- [ ] Create folders: `mkdir -p dbt/models/silver dbt/models/gold dbt/tests dbt/macros`
- [ ] dbt engine via uv: `uv add dbt-trino`
- [ ] dbt project initialized + connected to Trino
- [ ] `stg_customers`: blank `TotalCharges` fixed explicitly, Yes/No → boolean, snake_case columns
- [ ] `stg_tickets` + `stg_payments`: typed, deduped
- [ ] Email/phone masked (hash or partial)
- [ ] Bad rows go to `rejected_rows` **with a rejection reason** — never silently dropped
- [ ] dbt tests: unique, not_null, accepted_values on Silver
- [ ] `dbt test` all green
- [ ] Every rejected row has an explanation you can say out loud

**Done when:** `dbt test` passes + zero unexplained rejects.

**Commit:** `feat: refinery — silver models, masking, quarantine, tests`

---

## Phase 5 — 🏅 Goldsmith (dbt Gold: 360, risk, validation)

- [ ] `customer_360`: one row per customer = spend, tickets, satisfaction, failed payments, tenure, contract
- [ ] `customer_risk`: the 5-point rule + reasons column ("month-to-month, 2 failed payments")
- [ ] `monthly_revenue`: revenue by month
- [ ] `risk_validation`: real churn rate per score band
- [ ] Churn rate rises monotonically across bands (high-risk churns clearly more) — if not, retune the points

**Done when:** high-risk band visibly churns more than low-risk (the proof of the rules).

**Commit:** `feat: goldsmith — customer_360, risk score, validation`

---

## Phase 6 — 📊 Showcase (Superset, minimized)

- [ ] Create folder: `mkdir superset` (its compose file lives there)
- [ ] Superset in Docker on :8088, admin user created
- [ ] Trino driver installed in the Superset container
- [ ] Connection: `trino://...@trino:8080/iceberg/gold`
- [ ] 4 datasets registered: customer_360, customer_risk, monthly_revenue, risk_validation
- [ ] 4 charts: revenue line · customers per risk band · churn rate per band · top-20 risky table
- [ ] 1 dashboard with all 4 + screenshot in `docs/screenshots`
- [ ] **Stop here — no decorating.** Value is in Phases 4/7, not chart colors.

**Done when:** dashboard shows 4 charts + churn-per-band matches `risk_validation`.

**Commit:** `feat: showcase — superset churn dashboard`

---

## Phase 7 — 🕹 Ops Room (Airflow + CI, minimized)

- [ ] Create folders: `mkdir orchestration .github/workflows`
- [ ] Airflow in Docker on :8081
- [ ] Daily DAG at 02:00: `ingest → silver → gold` with dbt tests between layers, `retries=2`
- [ ] Freshness check: Gold older than 24h ⇒ task failure
- [ ] Failure alert: webhook (plain curl is fine — Slack optional)
- [ ] Weekly maintenance DAG: Iceberg expire snapshots + remove orphan files
- [ ] GitHub Actions: dbt tests on every PR
- [ ] **Break something on purpose → alert fires → fix → rerun**

**Done when:** a deliberate failure produces an alert.

**Commit:** `feat: ops room — airflow dag, freshness sla, alerts, ci`

---

## Phase 8 — 🚀 Launch (docs + story)

- [ ] README: architecture diagram (draw.io/Excalidraw or mermaid) + quickstart a stranger can run
- [ ] Screenshots incl. Superset dashboard
- [ ] Short "what I broke and what I learned" section (use your Phase 1 break note)
- [ ] Optional: 2-minute demo video
- [ ] Stranger-test: fresh clone + README instructions → working dashboard

**Done when:** a stranger can clone → `docker compose up` → dashboard.

**Commit:** `docs: launch — readme, screenshots, lessons`
