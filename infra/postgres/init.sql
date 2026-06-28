CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
    CREATE TYPE user_role AS ENUM ('admin', 'reviewer', 'user');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'document_repository') THEN
    CREATE TYPE document_repository AS ENUM ('pending_review', 'certified', 'rejected', 'archived');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'processing_status') THEN
    CREATE TYPE processing_status AS ENUM (
      'uploaded', 'ocr_in_progress', 'ocr_complete', 'extraction_in_progress', 'extraction_complete',
      'embedded', 'ready_for_review', 'failed',
      'parsing', 'structuring', 'classifying', 'awaiting_certification', 'schema_extraction',
      'embedding', 'processing_complete'
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'review_final_status') THEN
    CREATE TYPE review_final_status AS ENUM ('in_review', 'reviewer_approved', 'certified', 'rejected');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'query_message_role') THEN
    CREATE TYPE query_message_role AS ENUM ('user', 'assistant');
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email VARCHAR(255) UNIQUE NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  name VARCHAR(255) NOT NULL,
  role user_role NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  original_filename VARCHAR(500) NOT NULL,
  s3_path VARCHAR(1000) NOT NULL,
  current_repository document_repository NOT NULL DEFAULT 'pending_review',
  processing_status processing_status NOT NULL DEFAULT 'uploaded',
  uploaded_by UUID NOT NULL REFERENCES users(id),
  make VARCHAR(255),
  model VARCHAR(255),
  year INTEGER,
  warranty_type VARCHAR(255),
  country VARCHAR(255),
  metadata_json JSONB DEFAULT '{}'::jsonb,
  confidence_score FLOAT,
  error_message TEXT,
  uploaded_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  document_type VARCHAR(64),
  master_schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
  document_tree_json JSONB NOT NULL DEFAULT '[]'::jsonb,
  completeness FLOAT
);

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

CREATE TABLE IF NOT EXISTS reviews (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  document_id UUID UNIQUE NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  reviewer_id UUID REFERENCES users(id),
  reviewer_approved_at TIMESTAMP,
  reviewer_comment TEXT,
  admin_id UUID REFERENCES users(id),
  admin_approved_at TIMESTAMP,
  admin_comment TEXT,
  rejected_by UUID REFERENCES users(id),
  rejection_reason TEXT,
  final_status review_final_status NOT NULL DEFAULT 'in_review',
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS query_sessions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES users(id),
  title VARCHAR(255) NOT NULL DEFAULT 'New Session',
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  last_message_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS query_messages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id UUID NOT NULL REFERENCES query_sessions(id) ON DELETE CASCADE,
  role query_message_role NOT NULL,
  content TEXT NOT NULL,
  evidence_json JSONB,
  confidence_score FLOAT,
  metadata_filters_applied_json JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS support_tickets (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  document_id UUID REFERENCES documents(id) ON DELETE SET NULL,
  session_id UUID REFERENCES query_sessions(id) ON DELETE SET NULL,
  raised_by UUID REFERENCES users(id),
  question TEXT,
  answer_snapshot TEXT,
  note TEXT,
  status VARCHAR(24) NOT NULL DEFAULT 'open',
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES users(id),
  action VARCHAR(255) NOT NULL,
  target_type VARCHAR(255) NOT NULL,
  target_id UUID,
  metadata_json JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

ALTER TABLE documents ADD COLUMN IF NOT EXISTS required_fields_missing BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS ai_summary_text        TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS section_extracts_json  JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS document_sections_json JSONB NOT NULL DEFAULT '[]'::jsonb;

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

INSERT INTO users (email, password_hash, name, role)
VALUES
  ('admin@demo.com', '$2b$10$.Wf0QAnOn2x4X5CGovfTteECQj5/0f1mQ9Ycf6MzW6S8EcA4wsv9.', 'Demo Admin', 'admin'),
  ('reviewer@demo.com', '$2b$10$6x9h6dQ8v5mXHg19K8mR8e9z5Md8SOWHSG4h5S9jcwjdR4QhP9r2a', 'Demo Reviewer', 'reviewer'),
  ('user@demo.com', '$2b$10$4a3qDWS2v1d0fR4CWjY9QOwW.JNDS0G4W2wGX8WbR2rAHnY0dOq8e', 'Demo User', 'user')
ON CONFLICT (email) DO NOTHING;
