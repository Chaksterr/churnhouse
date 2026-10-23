# churnhouse — The Concepts Playbook

Every concept you will meet in this project, explained properly:
**What it is → the problem it solves → how churnhouse shows it → the interview question you must be able to answer.**

Read a section **before** doing the matching phase. Return to it after, and answer the question out loud — if you can't, the phase isn't done yet.

---

## 1 — Data architecture fundamentals

### 1.1 OLTP vs OLAP
- **What:** OLTP systems (transactional: the CRM, the billing app) are built for *many small writes* — "insert one payment row", "update one customer". OLAP systems (analytics: our warehouse) are built for *few huge reads* — "sum all revenue by month for 7,000 customers".
- **The problem:** one database can't do both well. Analytics queries on the live CRM would slow down the business app.
- **In churnhouse:** the 3 CSVs simulate the exports you'd pull out of OLTP systems. Everything from Bronze onward is OLAP territory.
- **Interview Q:** "Why not analyze the production database directly?" (Answer: load, locking, schema shape, history, cost.)

### 1.2 ETL vs ELT
- **What:** ETL = Transform the data *before* loading it into the warehouse. ELT = Load raw *first*, transform *inside* the warehouse (Trino + dbt do the transforming).
- **Why ELT won:** modern storage (S3) is cheap and engines (Trino) are fast, so you no longer need to decide "what to keep" on the way in. **Raw first = replayable forever.** Also: transformation bugs no longer destroy your only copy.
- **In churnhouse:** dlt loads the CSVs untouched (Bronze), dbt transforms them afterwards (Silver, Gold). That order *is* ELT.
- **Interview Q:** "What do you lose with ELT?" (Answer: storage cost of raw data + the need for a real transforming engine — which we have.)

### 1.3 The medallion architecture (Bronze → Silver → Gold)
- **What:** three zones, each with a *contract*:
  - **Bronze** = raw reality. Append-only, audited (`ingested_at`, `source_file`). Nobody cleans here. It is the *evidence*.
  - **Silver** = clean, typed, deduplicated, PII-masked, one row per entity. Quality gates (dbt tests) live here.
  - **Gold** = business models: pre-joined, pre-aggregated, ready for dashboards/analysts.
- **The problem it solves:** without zones, a cleaning mistake *destroys* your source data and nobody knows what the numbers mean anymore. With zones: every downstream table can be rebuilt from Bronze — you always have a reset button.
- **In churnhouse:** `iceberg.bronze.*`, `iceberg.silver.*`, `iceberg.gold.*` — literally one schema per zone.
- **Interview Q:** "Cleaning happens where, and why never in Bronze?" (Answer: Silver, because Bronze's contract is *fidelity* — the moment you edit raw rows you lose replayability and audit.)

### 1.4 Single source of truth
- **What:** one table (or one layer) that is *the* official version of a fact — other things derive from it.
- **In churnhouse:** Silver `stg_customers` is the truth for "who is the customer"; Gold `customer_360` is the truth for "what do we know about them today". Two analysts must never compute churn differently — they both read Gold.
- **Interview Q:** "Analyst A and B get different churn numbers. What do you do?" (Answer: find the fan-out point; usually someone built a private spreadsheet/query instead of reading the Gold layer.)

### 1.5 Batch vs streaming
- **What:** batch = process on a schedule (daily 02:00). Streaming = process continuously as events arrive (Kafka).
- **Decision rule:** business question granularity decides it. "Who might churn *this week*?" = batch is fine. "Cancel this subscription *now*" = streaming.
- **In churnhouse:** batch — and that's a *legitimate architecture*, not a compromise. The enterprise upgrade path (later) is CDC (Debezium) streaming the CRM database into Bronze; Bronze's append-only design survives that change unchanged.
- **Interview Q:** "Why batch, when did you choose it?" (Answer: daily decisions, small volume, cost. Name the CDC upgrade and you sound senior.)

---

## 2 — Storage & the lakehouse (Phase 1)

### 2.1 Object storage (S3/MinIO)
- **What:** giant flat key-value store. You PUT/GET objects (files) by path: `warehouse/bronze/smoke_test/data/00001.parquet`. No "folders" really — just keys — and no SQL.millions of small "customers" table rows — files hold *pages of values*, one page per column.
- **Why it's the modern disk:** cheap, infinite, replicated 11-nines, every data tool speaks S3.
- **In churnhouse:** MinIO in Docker = our S3. Same API, local hardware.
- **Interview Q:** "What can you NOT do on object storage?" (Answer: efficient random row updates, atomic renames of directories, list-on-prefix at scale is also limited.)

### 2.2 File formats: why Parquet
- **What:** CSV = rows as text ("7590-VHVEG,Female,0,..."). Parquet = **columnar** binary: all values of a column are stored *together* on disk.
- **The problem:** CSV always reads *every* column even if you asked for one (and it's text-heavy, no real types). Parquet reads *only the columns you query* (column pruning / predicate pushdown) and stores types (int, timestamps) natively.
- **In churnhouse:** dlt/dbt/Trino writes Parquet under the hood; in Phase 1 you even look inside the files.
- **Interview Q:** "A query selects 3 columns of a 40-column table — what does Parquet let Trino skip?" (Answer: the other ~37 columns' pages entirely.)

### 2.3 What is a "table format" (Hive-style → Iceberg)
- **What:** file listings in a bucket are just... files. A **table format** is the *convention* that makes those files behave like one versioned SQL table: which files currently belong to the table, which are historical, what the columns/types are.
- **The problem table formats solve:** without them there's no ACID, no consistent schema, no rollback, no concurrent writes — just dangling files if anything crashes.
- **In churnhouse:** Iceberg is our table format; MinIO holds its files; Trino reads/writes through it.
- **Interview Q:** "Is Iceberg a file storing data?" — No, it is a metadata system that tells the engine *which files currently exist* on S3."
- **In churnhouse:** the REST catalog container (:8181). Trino asks it "which is the current metadata?" and the catalog *also* tells it how to reach the files (S3FileIO → MinIO).
- **Interview Q:** "What breaks if two REST catalogs point to the same bucket?" (Answer: nothing fatal, but writers drift apart — the bucket is the storage, the catalog namespace is ownership. Two catalogs = two parallel beliefs about what tables exist.)

### 2.4 The Iceberg file hierarchy — the heart of everything
Four levels, **each level points to the next**:

```
metadata.json            (1 per table version — says: current schema, partition spec,
  │                       current snapshot ID, list of historical snapshots)
  ↳ manifest list        (for each snapshot: the list of manifests + per-file partition
      │                   bounds = lets engines prune entire manifests)
        ↳ manifests      (lists data files + per-file column bounds, row counts →
            │             pruning per FILE on read = predicate pushdown)
              ↳ data files (Parquet — the only level holding actual rows)
```

- **Key insight:** *all writes = new files + a new metadata.json commit.* Nothing is overwritten in place — that's how you get time travel for free.
- **In churnhouse:** in Phase 1 you run INSERT, then UPDATE, then DELETE and watch the snapshots/files change each time; then you break one metadata.json *on purpose* and see what dies (engines can't resolve the table → metadata error, while the files sit orphaned).
- **Interview Q:** "A DELETE statement on an Iceberg table — what physically happens?" (Answer: a new snapshot whose metadata excludes the deleted rows' files (or rewrites the affected files); time travel can still see the old files until snapshot expiry.)

### 2.5 Snapshots & time travel
- **What:** every write produces a new *snapshot* = a consistent view of the table. "Read at snapshot N" = time travel (`FOR VERSION AS OF n` in Trino).
- **The problem:** in Hive tables, debugging "what did the dashboard show yesterday" is impossible. Here it's one query.
- **In churnhouse:** Phase 7's weekly DAG expires old snapshots to keep costs sane — retention is a *decision you set*.

### 2.6 Table maintenance (not optional in real life)
- **Expire snapshots**, **remove orphan files**, **compaction** (merge many tiny Parquet files into fewer bigger ones — file counts explode otherwise from many small writes).
- **In churnhouse:** the weekly maintenance DAG does the first two; min-retention is set to 0s for the lab (know why you'd *raise* it in prod: expensive recovery points!).
- **Interview Q:** "Someone deletes expired snapshots aggressively — what's lost?" (Answer: all time travel / accidental-corruption recovery to those points.)

### 2.7 The catalog decoupling: logic vs bytes
- **What:** the catalog stores *metadata pointers*; object storage stores *bytes*. Engines never "own" either.
- **Why:** swap engines (Trino ↔ Spark ↔ PyIceberg) without touching data — the catalog is the meeting point. That is *the* lakehouse design pattern.
- **In churnhouse:** REST catalog (the cloud-native API for this job).
- **Interview Q:** "Why a REST catalog instead of setting shared config in each engine?" (Answer: single brain, client-agnostic, avoids config drift; that's why Polaris/Glue/Unity all speak it.)

---

## 3 — Ingestion (Phases 2–3)

### 3.1 Write dispositions: append / merge / replace
- **append** = only add rows (history preserved) — **our Bronze rule**. `merge` = upsert on a key (slow-changing dimension territory); `replace` = rebuild one table.
- **Decision:** Bronze = append always. Silver/Gold = rebuilt by dbt, so ingestion never touches them.
- **Interview Q:** "How do you handle a source that re-sends yesterday's file nightly?" (Answer: append on purpose + dedupe *downstream* in Silver — never trust the source to be clean.)

### 3.2 Audit columns (`ingested_at`, `source_file`)
- **What:** metadata stamped on every row at load time.
- **Why:** the first question of every data incident is *what arrived when, and from where*. Without audit columns you debug with vibes.
- **In churnhouse:** dlt stamps them in Phase 3.

### 3.3 Idempotency & resumability
- **What:** running the loader twice must produce the *correct* end state — either new rows appended (our design: sources arrive pre-deduplicated) or nothing duplicated (merge mode).
- **The problem:** jobs crash at 03:00. You rerun. If your pipeline isn't idempotent, you've double-loaded today's data and hand-built a fake spike in the dashboards.
- **In churnhouse:** Phase 3's "run twice, counts correct" check; Airflow retries depend on this — retrying a non-idempotent task is sabotage.
- **Interview Q:** "Airflow retries a failed task mid-run. What saves you?" (Answer: idempotency design + checkpoints; dlt's state keeps it resumable rather than re-ingesting from zero.)

### 3.4 Schema inference & evolution (dlt)
- **What:** dlt reads a source, guesses types, creates tables — and when tomorrow's file has an extra column, it adds it (evolution) instead of crashing (breakage) or corrupting (guessing wrong).
- **The problem:** source owners don't warn you about column changes. Ever.
- **In churnhouse:** Phase 3 loads Telco + generated CSVs; the test for "what if a column appears" is easy to demo when you've *written* the generator (Phase 2 is yours — so you control the schema).
- **Interview Q:** "Source adds a NOT NULL column with no backfill — what's the sane pipeline response?" (Answer: land it in Bronze as null for old rows (append survives), let Silver's model + tests decide how/until when to trust it; escalate to the source owner via contract.)

### 3.5 Reproducible synthetic data (fixed seed)
- **What:** generators seeded at a fixed number produce byte-identical outputs every run.
- **Why:** your pipeline's tests need *stable known-bad cases* (e.g., the dup you planted on purpose). Random data each run = unreliable tests.
- **In churnhouse:** `generator/generate.py` (Phase 2) uses a fixed seed — the stranger-test in Phase 8 regenerates the same files on another laptop.

---

## 4 — Modeling & transformation (Phases 4–5)

### 4.1 Staging vs marts (dbt vocabulary: stg_ + fct/dim)
- **stg_ (staging)** = 1:1 reshaping of one source: rename columns (snake_case), cast types, dedupe, mask.
- **marts (fct_/dim_)** = business entities: joins + aggregations. Facts = events/measurements; dimensions = entities.
- **In churnhouse:** `stg_customers`/`stg_tickets`/`stg_payments` (Phase 4) then `customer_360`-shaped Gold marts (Phase 5).
- **Interview Q:** "Why ban business logic in staging?" (Answer: staging models stay 1:1 and dumb so every downstream model trusts identical inputs; mixing logic breaks the map between models and sources.)

### 4.2 Explicit handling of known dirt (the blank `TotalCharges`)
- **What:** every dataset has *systematic* flaws with a *known cause*. New customers have no accumulated charge yet → blank, not "data corruption".
- **The DE move:** make the hidden rule explicit — *treat blank TotalCharges as 0 with tenure = 0, or coalesce and comment* — and document it in the model itself.
- **Interview Q:** "A column is blank for 11 rows. Delete them?" (Answer: if the cause is legit (new customers), never delete — represent it. Delete only *unexplainable* garbage into quarantine.)

### 4.3 Deduplication
- **What/Why:** sources resend, retries duplicate, so row-level identity is your job: keep the latest (insert ordering), drop exact clones.
- **The SQL you'll actually write:** window functions — `row_number() over (partition by customer_id order by updated_at desc)` and filter `= 1`.
- **Interview Q:** "Which row do you keep when two have the same key + same updated_at?" (Answer: there's no correct answer without a deterministic tiebreaker (source control column, checksum, md5 of the row) — pick one and document it.)

### 4.4 SQL you must own
- CTEs (readable transform pipelines), window functions (`row_number`, `rank`, `sum() over (...)` for running metrics), `coalesce`/`try_cast`, `count_if`, case-when masks. Plus **joins discipline**: every join — what's the driving table, does it fan the grain, did you test it?

### 4.5 PII masking
- **What:** personal data (email, phone, names) must not walk to dashboards raw.
- **Approach ladder:** hash (deterministic — usable as join key), mask (`s*r@email.com`), or drop entirely when unused for the metric.
- **In churnhouse:** Phase 4 masks email/phone in Silver. Know the terms: *the analytics layer is NOT where PII lives.*
- **Interview Q:** "Why hash email rather than "not store it?" (Answer: even hashed has to serve join purposes — but note the right answer is a *column-minimal design* first, masking second — masking is not a stack strategy.)

### 4.6 One row per entity — the 360 view
- **What:** joining 3 source systems into *one* row per customer defined at a defined granularity.
- **The danger:** a join fans out (customer × tickets × payments = nonsense). The fix: *aggregate in subqueries first* (tickets→`ticket_count, avg_satisfaction`; payments→`failed_payment_count`), join on a stable key.
- **In churnhouse:** `customer_360` (Phase 5) is exactly this design.
- **Interview Q:** "Before joining tickets to customers, what must you compute first?" (Answer: the per-customer aggregate of tickets — never join the event table directly into the profile grain.)

### 4.7 Rule-based scoring + reasons (explainability)
- **What:** transparent point systems (contract +2, tenure +2, tickets +1, satisfaction +1, failed payments +2) instead of an opaque model. Reasons like `month-to-month, 2 failed payments` are *saved next to the score*.
- **Why it matters (DE-specific):** a score nobody can explain gets distrusted *and* unmaintainable. Saving the reasons enables the audit chart (`risk_validation`) and the "why is this customer flagged?" follow-up.
- **Interview Q:** "Why save reasons *inside* the table rather than recompute?" (Answer: reproducibility + explainability: the evaluation chart reads the exact reason set the score was computed from, at row level.)

### 4.8 The feedback loop (`risk_validation`)
- **What:** compare *predicted* risk bands X-axis against *observed* churn rate Y-axis. If churn rises with score — rules work.
- **The deep idea:** a DE pipeline isn't done when it runs — it's done when a *business claim is verified with data*.
- **Interview Q:** "High-risk band churns the same as the low-risk one — what do you do?" (Answer: rules wrong or validation wrong — check weights and the data first; retune points, rerun, document.)

---

## 5 — Data quality (Phases 4 & 7)

### 5.1 Tests as contracts
- unique, not_null, accepted_values (e.g., `contract ∈ {…}`), relationships (referential checks). They run per commit; check-ins prevent the failures the data world ships silently.
- **Interview Q:** "Difference between a test failing and data being 'odd'?" (Answer: a test = a *contract and known expectations* (schema/type patterns you enforce); odd = unchecked anomaly (to be made into a test, or handled by anomaly tooling later).

### 5.2 Quarantine (rejected_rows), never silent deletion
- **What:** failing rows go to a separate table with a machine-readable reason + the source row.
- **Why:** deleting = *lying by absence*. Quarantine preserves (a) a trace of *what arrived*, (b) *what failed*, (c) the audit trail to improve rules over time.
- **In churnhouse:** Silver ships every bad row *with reason* — and Phase 4's done-check literally is "I can explain every row in there".

### 5.3 Freshness SLA ("Gold older than 24h fails")
- **What:** a *data SLA*: if the daily build failed or was never run, the dashboard shows stale numbers *unless the task fails*.
- **Interview Q:** "What silently breaks trust that a pipeline technically 'works'?" (Answer: correct data being *not fresh* — its consumers don't know. That's why freshness is an automated check, not a dashboard footnote.)

### 5.4 Fail loud, alert, page
- Silent-wrong is the worst failure mode: the pipeline "worked" noemail went out, dashes show fiction. So the pipeline *itself* asserts freshness and fires a webhook (Phase 7) instead of letting users find out.

---

## 6 — Orchestration (Phase 7)

### 6.1 The DAG (Directed Acyclic Graph)
- **What:** your tasks as a graph (`ingest → silver → gold`), no cycles. Airflow schedules/executes it.
- **Interview Q:** "Why is DAG-scheduled better than a `pipeline.sh` in cron?" (Answer: dependencies, backfills, logging, retries, monitoring/UI — everything cron has none of.)

### 6.2 Retries × idempotency × backfills
- Transient failures (network blips) = retry; logic failures = don't hide with retries. Retrying is only safe when the task is idempotent.

### 6.3 SLA versus sequencing
- Sequencing (Bronze before Silver, especially dbt test gates between layers) *prevents* bad-merit data flows; SLA/freshness tasks *measure* (a late run fails even when idempotent succeeded).
- **Interview Q:** "dbt test fails after Silver: does Gold run?" — No (that's the whole orchestration point — blockage in the DAG refuses downstream).

### 6.4 CI/CD for data
- CI: every PR runs `dbt test` against the dev environment before any merge → broken transformations never reach prod.
- CD (beyond ours): deploy the PR's dbt code into prod environments via pipeline; rollback = revert commit.
- **Interview Q:** "We only have CI here — describe the missing CD half."
- **Bonus:** Weekly maintenance DAG (expire snapshots, remove orphan files) — a *table-format* operations task, i.e., real DE operators need more than pipeline runs.

### 6.5 Secrets hygiene
- `.env` gitignored, `.env.example` committed, "which values SHOWED up where" traceability. Note the learning-connect: catalog/properties files read env — the pattern ${ENV:VAR} keeps secrets out of the code.

---

## 7 — Engineering craft (all phases)

- **Git story:** one commit per phase with *clean meaning* (`feat: refinery — silver models, masking, tests`). Recruiters read history; the commit trail *is* the story.
- **Pinned versions everywhere:** Trino `470` (never `latest` for engines), `uv.lock` for Python. Reproducibility = interview pass on "why do these don't collide in prod?"
- **The stranger test:** from clone → working dashboard (this includes the manual `warehouse` bucket step + fixed-seed generator). If setup requires undocumented tribal knowledge, it's not done.
- **Incidents as story:** you *break* something on purpose in Phases 1 & 7 — the Phase 8 "what I broke and what I learned" is interview gold.
- **Honest limitation list (enterprise gap analysis):** D1 (dev/sting/prod), secrets manager, RBAC column-level Pri, lineage (DataHub/OpenMetadata), CDC/Streaming, DQ frameworks (Great Expectations/Soda), pytest/ruff — *know them by name and why your project doesn't have them in that scope.* "I'd replace MinIO with real S3, .env with Vault, add env promotion + lineage" = a senior-sounding sentence listing the exact changes of scope.

---

## One-line glossary (fast revision)

| Term | One line |
|---|---|
| OLTP / OLAP | Transactional write-optimized online vs analytics read-optimized |
| ETL / ELT | Transform-before-load vs load-raw-then-transform-in-engine |
| Medallion | Bronze raw copy, Silver clean & tested, Gold business-ready |
| Iceberg | Table format = versioned metadata over Parquet files on S3 |
| REST catalog | The central service engines ask "which tables exist + where is metadata" |
| Snapshot | One consistent version of a table; every write = a new snapshot |
| Manifest | Metadata listing data files + column bounds for pruning |
| dlt | Python ingestion library: sources → destinations, schema evolution + append/merge |
| dbt | SQL transformation framework + tests in version control |
| write disposition | append/merge/replace = how new data lands |
| Quarantine | Bad rows → separate table with reason, never delete |
| Freshness SLA | "Data must be ≤ X hours old or alert/fail" |
| DAG | Task dependencies as a graph; Airflow executes + schedules it |
| idempotent | Rerunning produces correct state, not duplicates |
| time travel | Query table as of an earlier snapshot |
| compaction | Merge small files into larger ones; cheaper scans |
| stage/mart | 1:1 cleaning models vs business-joined business models |
| rejected_rows | Quarantine table of bad rows with reasons |
