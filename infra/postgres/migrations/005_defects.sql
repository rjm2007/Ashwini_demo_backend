-- 005_defects.sql
-- defects / defect_messages — missing from init.sql and every other migration file.
\set ON_ERROR_STOP on

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'defect_message_role') THEN
    CREATE TYPE defect_message_role AS ENUM ('user', 'assistant');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS defects (
  id                        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  document_id               UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  created_by                UUID NOT NULL REFERENCES users(id),
  reported_defect           TEXT NOT NULL,
  purchase_date             DATE,
  current_mileage           INTEGER,
  make                      VARCHAR,
  warranty_type             VARCHAR(20),
  model                     VARCHAR,
  year                      INTEGER,
  primary_decision          VARCHAR,
  primary_component         VARCHAR,
  primary_coverage_id       VARCHAR,
  overall_confidence_score  FLOAT,
  context_json              JSONB,
  created_at                TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at                TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS defect_messages (
  id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  defect_id        UUID NOT NULL REFERENCES defects(id) ON DELETE CASCADE,
  role             defect_message_role NOT NULL,
  content          TEXT NOT NULL,
  evidence_json    JSONB,
  confidence_score FLOAT,
  created_at       TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_defects_document ON defects(document_id);
CREATE INDEX IF NOT EXISTS idx_defect_messages_defect ON defect_messages(defect_id);
