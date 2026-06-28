-- WARR-1172 schema v2: cost tracking + applicability indexes

CREATE TABLE IF NOT EXISTS cost_events (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  document_id   UUID REFERENCES documents(id) ON DELETE CASCADE,
  session_id    UUID REFERENCES query_sessions(id) ON DELETE SET NULL,
  stage         VARCHAR(32) NOT NULL,
  provider      VARCHAR(32) NOT NULL,
  model         VARCHAR(64) NOT NULL,
  input_tokens  INTEGER,
  output_tokens INTEGER,
  units         FLOAT,
  unit_kind     VARCHAR(16),
  usd_cost      NUMERIC(12,6) NOT NULL DEFAULT 0,
  created_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cost_events_doc  ON cost_events(document_id);
CREATE INDEX IF NOT EXISTS idx_cost_events_sess ON cost_events(session_id);
CREATE INDEX IF NOT EXISTS idx_cost_events_day  ON cost_events((date_trunc('day', created_at)));

CREATE INDEX IF NOT EXISTS idx_documents_applicability
  ON documents USING gin ((master_schema_json -> 'applicability'));

CREATE INDEX IF NOT EXISTS idx_documents_schema_make
  ON documents (((master_schema_json -> 'applicability' ->> 'make')));
