-- Central GTM data layer. Written for SQLite (local/dev) and portable to
-- Postgres/Snowflake/BigQuery with type tweaks noted inline.
-- Design rules:
--   * accounts keyed by normalised domain (natural key) + surrogate id
--   * every golden record keeps lineage back to source records
--   * scores are append-only history; "current" is a view
--   * operational tables (job_runs, dead_letter, webhook_events) make the
--     pipelines observable and idempotent

CREATE TABLE IF NOT EXISTS accounts (
    account_id      INTEGER PRIMARY KEY,           -- BIGSERIAL in Postgres
    domain          TEXT NOT NULL UNIQUE,          -- normalised, e.g. acme.com
    name            TEXT,
    industry        TEXT,
    employees       INTEGER,
    country         TEXT,                          -- ISO-3166 alpha-2
    owner_email     TEXT,                          -- assigned rep
    tech_stack      TEXT,                          -- JSON array (ARRAY/VARIANT elsewhere)
    crm_external_id TEXT,                          -- id in HubSpot/Salesforce
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS contacts (
    contact_id      INTEGER PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,          -- normalised lowercase
    account_id      INTEGER REFERENCES accounts(account_id),
    first_name      TEXT,
    last_name       TEXT,
    title           TEXT,
    seniority       TEXT CHECK (seniority IN ('c_level','vp','director','manager','ic')),
    crm_external_id TEXT,
    created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_contacts_account ON contacts(account_id);

-- Buying committee: a contact's role on a specific account's deal.
-- Separate table because roles are per-opportunity judgements, can be
-- set by a rep (source='rep') overriding the title-based guess (source='rule').
CREATE TABLE IF NOT EXISTS buying_committee (
    account_id  INTEGER NOT NULL REFERENCES accounts(account_id),
    contact_id  INTEGER NOT NULL REFERENCES contacts(contact_id),
    role        TEXT NOT NULL CHECK (role IN ('economic_buyer','champion','technical_evaluator','end_user','blocker')),
    source      TEXT NOT NULL DEFAULT 'rule' CHECK (source IN ('rule','rep','ai')),
    confidence  REAL,
    updated_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (account_id, contact_id, role)
);

-- Raw source records + which golden record they resolved to (lineage/debug).
CREATE TABLE IF NOT EXISTS source_records (
    source        TEXT NOT NULL,                   -- crm | enrichment | clay | apollo | form ...
    source_id     TEXT NOT NULL,
    entity_type   TEXT NOT NULL CHECK (entity_type IN ('account','contact')),
    golden_key    TEXT NOT NULL,                   -- domain or email
    payload       TEXT NOT NULL,                   -- raw JSON
    ingested_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source, source_id, entity_type)
);

CREATE TABLE IF NOT EXISTS signals (
    signal_id    INTEGER PRIMARY KEY,
    domain       TEXT NOT NULL,
    type         TEXT NOT NULL,
    occurred_at  TEXT NOT NULL,
    detail       TEXT,
    source       TEXT,
    dedupe_key   TEXT NOT NULL UNIQUE              -- hash(domain,type,occurred_at,detail)
);
CREATE INDEX IF NOT EXISTS ix_signals_domain_time ON signals(domain, occurred_at);

CREATE TABLE IF NOT EXISTS account_scores (
    account_id    INTEGER NOT NULL REFERENCES accounts(account_id),
    scored_at     TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    model_version TEXT NOT NULL,                   -- hash of scoring config
    fit_score     REAL NOT NULL,
    intent_score  REAL NOT NULL,
    score         REAL NOT NULL,
    tier          TEXT NOT NULL,
    reasons       TEXT NOT NULL,                   -- JSON array of strings
    PRIMARY KEY (account_id, scored_at)
);

CREATE VIEW IF NOT EXISTS current_account_scores AS
SELECT s.* FROM account_scores s
JOIN (SELECT account_id, MAX(scored_at) AS m FROM account_scores GROUP BY account_id) l
  ON s.account_id = l.account_id AND s.scored_at = l.m;

CREATE TABLE IF NOT EXISTS routing_assignments (
    lead_id      TEXT PRIMARY KEY,
    account_id   INTEGER REFERENCES accounts(account_id),
    assigned_to  TEXT NOT NULL,
    rule         TEXT NOT NULL,                    -- which rule fired (auditability)
    tier         TEXT,
    sla_due_at   TEXT,
    first_touch_at TEXT,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------- operational tables ----------
CREATE TABLE IF NOT EXISTS job_runs (
    run_id       TEXT PRIMARY KEY,
    job_name     TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('running','success','failed','skipped')),
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    attempts     INTEGER NOT NULL DEFAULT 1,
    records_in   INTEGER,
    records_out  INTEGER,
    error        TEXT
);
CREATE INDEX IF NOT EXISTS ix_job_runs_name_time ON job_runs(job_name, started_at);

CREATE TABLE IF NOT EXISTS dead_letter (
    id           INTEGER PRIMARY KEY,
    job_name     TEXT NOT NULL,
    payload      TEXT NOT NULL,
    error        TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    replayed_at  TEXT
);

CREATE TABLE IF NOT EXISTS webhook_events (
    event_id     TEXT PRIMARY KEY,                 -- provider's id => idempotency
    provider     TEXT NOT NULL,
    received_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT,
    payload      TEXT NOT NULL
);

-- ---------- handy views for reps / dashboards ----------
CREATE VIEW IF NOT EXISTS committee_coverage AS
SELECT a.account_id, a.domain, a.name,
       SUM(CASE WHEN bc.role='economic_buyer' THEN 1 ELSE 0 END)      AS economic_buyers,
       SUM(CASE WHEN bc.role='champion' THEN 1 ELSE 0 END)            AS champions,
       SUM(CASE WHEN bc.role='technical_evaluator' THEN 1 ELSE 0 END) AS technical_evaluators,
       SUM(CASE WHEN bc.role='end_user' THEN 1 ELSE 0 END)            AS end_users
FROM accounts a LEFT JOIN buying_committee bc ON bc.account_id = a.account_id
GROUP BY a.account_id, a.domain, a.name;
