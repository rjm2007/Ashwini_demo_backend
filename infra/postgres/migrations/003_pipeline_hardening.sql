-- 003_pipeline_hardening.sql
-- Adds document_sections_json column and performance indexes

ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_sections_json JSONB NOT NULL DEFAULT '[]'::jsonb;

-- pipeline_events: composite index for tail-since-sequence queries
CREATE INDEX IF NOT EXISTS idx_pipeline_events_doc_seq
  ON pipeline_events(document_id, sequence);

-- documents: partial index for required_fields_missing queries
CREATE INDEX IF NOT EXISTS idx_documents_required_missing
  ON documents(required_fields_missing)
  WHERE required_fields_missing = TRUE;
