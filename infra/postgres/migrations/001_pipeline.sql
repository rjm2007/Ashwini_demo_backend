-- Migration 001 — Pipeline schema additions
-- Run: psql $DATABASE_URL -f infra/postgres/migrations/001_pipeline.sql
\set ON_ERROR_STOP on

DO $$ BEGIN
  ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'parsing';
  ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'structuring';
  ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'classifying';
  ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'awaiting_certification';
  ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'schema_extraction';
  ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'embedding';
  ALTER TYPE processing_status ADD VALUE IF NOT EXISTS 'processing_complete';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_type VARCHAR(64);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS master_schema_json JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_tree_json JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS completeness FLOAT;

CREATE TABLE IF NOT EXISTS pipeline_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  act SMALLINT NOT NULL,
  stage VARCHAR(64) NOT NULL,
  step_key VARCHAR(128) NOT NULL,
  step_label VARCHAR(255) NOT NULL,
  status VARCHAR(16) NOT NULL,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  duration_ms INTEGER,
  sequence INTEGER NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_doc ON pipeline_events(document_id, sequence);
CREATE INDEX IF NOT EXISTS idx_pipeline_events_status ON pipeline_events(document_id, status);

-- support_tickets requires query_sessions — see 002_missing_tables.sql or init.sql (fixed order)
