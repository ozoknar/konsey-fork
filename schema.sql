-- Konsey Audit / Memory Şeması — Anayasa EK-C (DuckDB 1.5.x)
-- KURAL: Yalnızca INSERT (append-only, Madde 10.1). UPDATE/DELETE YASAK.
-- Session kapanışı UPDATE değil, council_messages'a 'session_end' event'i olarak eklenir.

CREATE TABLE IF NOT EXISTS council_sessions (
  session_id      UUID PRIMARY KEY DEFAULT uuid(),
  topic           TEXT NOT NULL,
  risk_profile    TEXT NOT NULL,            -- public/internal/pii/phi/production
  budget_usd      DECIMAL(10,2),
  max_iter        INTEGER,
  max_wall_time_s INTEGER,
  status          TEXT,                      -- preflight/planning/.../done/aborted
  started_at      TIMESTAMP DEFAULT now(),
  ended_at        TIMESTAMP,                 -- mutate edilmez; kapanış event ile (bkz. council_messages)
  cost_actual_usd DECIMAL(10,2),
  user_id         TEXT
);

CREATE TABLE IF NOT EXISTS council_messages (
  msg_id          UUID PRIMARY KEY DEFAULT uuid(),
  session_id      UUID,
  from_agent      TEXT NOT NULL,             -- claude|codex|google|orchestrator|human
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
  evidence_type   TEXT,   -- test_pass|terminal_exit|url_check|static_analysis|human_approval
  source          TEXT,
  content_hash    TEXT,
  produced_by     TEXT,
  verified_by     TEXT,
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
  violation_type  TEXT,   -- madde13_phi_leak|budget_overrun|tool_failure|...
  detail          TEXT,
  ts              TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_msg_session_ts ON council_messages(session_id, ts);
CREATE INDEX IF NOT EXISTS idx_ev_session     ON council_evidence(session_id);
CREATE INDEX IF NOT EXISTS idx_dec_session    ON council_decisions(session_id);
CREATE INDEX IF NOT EXISTS idx_dis_session    ON council_dissent(session_id);
