-- Council append-only audit schema (Constitution Article 10) — DuckDB.
-- POLICY: INSERT only. No UPDATE, no DELETE (Article 10.1). A session is never
-- mutated to "closed" — closure is appended to council_messages as a
-- 'session_end' event instead. The INSERT-only rule is enforced at the app layer
-- (audit.py / cli_helpers/konsey_db.py) and surfaced by `council doctor`.
--
-- 6 tables: sessions, messages, evidence, decisions, dissent, incidents.
-- All identity-bearing columns are generic: user_id = cfg.owner ("operator"
-- default), agent names are logical roster names (lead/critic/verifier/...),
-- never a brand or a machine username. A SQLite variant is left as a commented
-- TODO at the end for installs without a DuckDB wheel.

CREATE TABLE IF NOT EXISTS council_sessions (
  session_id      UUID PRIMARY KEY DEFAULT uuid(),
  topic           TEXT NOT NULL,
  risk_profile    TEXT NOT NULL,             -- public|internal|pii|phi|production
  budget_usd      DECIMAL(10,2),
  max_iter        INTEGER,
  max_wall_time_s INTEGER,
  status          TEXT,                      -- preflight|planning|...|done|aborted
  started_at      TIMESTAMP DEFAULT now(),
  ended_at        TIMESTAMP,                 -- never mutated; closure is a 'session_end' message event
  cost_actual_usd DECIMAL(10,2),
  user_id         TEXT                       -- = cfg.owner ("operator" default); never the machine username
);

CREATE TABLE IF NOT EXISTS council_messages (
  msg_id          UUID PRIMARY KEY DEFAULT uuid(),
  session_id      UUID,
  from_agent      TEXT NOT NULL,             -- logical roster name | orchestrator | human
  to_agent        TEXT,
  msg_type        TEXT,                      -- plan|critique|vote|result|dissent|session_start|session_end|lifecycle
  payload         JSON,
  content_hash    TEXT,
  ts              TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS council_evidence (
  evidence_id     UUID PRIMARY KEY DEFAULT uuid(),
  session_id      UUID,
  task_id         UUID,
  evidence_type   TEXT,                      -- test_pass|terminal_exit|url_check|static_analysis|human_approval
  source          TEXT,
  content_hash    TEXT,
  produced_by     TEXT,
  verified_by     TEXT,                      -- producer != verifier invariant (Article 2.4)
  ts              TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS council_decisions (
  decision_id     UUID PRIMARY KEY DEFAULT uuid(),
  session_id      UUID,
  decision        TEXT,
  confidence      FLOAT,
  evidence_refs   JSON,
  dissent_refs    JSON,
  human_approved  BOOLEAN,
  ts              TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS council_dissent (
  dissent_id       UUID PRIMARY KEY DEFAULT uuid(),
  session_id       UUID,
  agent            TEXT NOT NULL,
  against_decision UUID,
  rationale        TEXT,
  ts               TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS council_incidents (
  incident_id     UUID PRIMARY KEY DEFAULT uuid(),
  session_id      UUID,
  violation_type  TEXT,                      -- phi_leak|budget_overrun|tool_failure|...
  detail          TEXT,
  ts              TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_msg_session_ts ON council_messages(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_ev_session     ON council_evidence(session_id);
CREATE INDEX IF NOT EXISTS idx_dec_session    ON council_decisions(session_id);
CREATE INDEX IF NOT EXISTS idx_dis_session    ON council_dissent(session_id);

-- TODO (SQLite variant, for installs without a DuckDB wheel): replace UUID with
-- TEXT + application-generated uuid4(), JSON with TEXT, DECIMAL with REAL, and
-- now() with CURRENT_TIMESTAMP. Behaviour (append-only) is identical.
