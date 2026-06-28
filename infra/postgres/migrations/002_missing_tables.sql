-- Repair partial init: creates tables that failed when support_tickets ran before query_sessions
\set ON_ERROR_STOP on

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'review_final_status') THEN
    CREATE TYPE review_final_status AS ENUM ('in_review', 'reviewer_approved', 'certified', 'rejected');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'query_message_role') THEN
    CREATE TYPE query_message_role AS ENUM ('user', 'assistant');
  END IF;
END $$;

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

INSERT INTO users (email, password_hash, name, role)
VALUES
  ('admin@demo.com', '$2b$10$.Wf0QAnOn2x4X5CGovfTteECQj5/0f1mQ9Ycf6MzW6S8EcA4wsv9.', 'Demo Admin', 'admin'),
  ('reviewer@demo.com', '$2b$10$6x9h6dQ8v5mXHg19K8mR8e9z5Md8SOWHSG4h5S9jcwjdR4QhP9r2a', 'Demo Reviewer', 'reviewer'),
  ('user@demo.com', '$2b$10$4a3qDWS2v1d0fR4CWjY9QOwW.JNDS0G4W2wGX8WbR2rAHnY0dOq8e', 'Demo User', 'user')
ON CONFLICT (email) DO NOTHING;
