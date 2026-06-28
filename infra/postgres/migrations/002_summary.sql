-- Migration 002: Add summary and extraction columns
ALTER TABLE documents ADD COLUMN IF NOT EXISTS required_fields_missing BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ai_summary_text        TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS section_extracts_json  JSONB NOT NULL DEFAULT '[]'::jsonb;
