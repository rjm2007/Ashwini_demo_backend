-- 009_app_settings.sql
-- Runtime-editable application settings, currently used only for API keys
-- entered through the admin "API Keys" screen.
--
-- Values are stored ENCRYPTED (AES-256-GCM, see backend/src/modules/app-settings/
-- crypto.util.ts). The column holds the opaque envelope string, never plaintext,
-- so a database dump does not leak provider credentials. `is_secret` drives
-- whether the API masks the value on read.
\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS app_settings (
  setting_key      VARCHAR(64) PRIMARY KEY,
  encrypted_value  TEXT        NOT NULL,
  is_secret        BOOLEAN     NOT NULL DEFAULT TRUE,
  updated_by       UUID        REFERENCES users(id),
  updated_at       TIMESTAMP   NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE  app_settings IS 'Runtime-editable settings. Values are AES-256-GCM encrypted envelopes, never plaintext.';
COMMENT ON COLUMN app_settings.encrypted_value IS 'Format: v1:<iv_b64>:<authTag_b64>:<ciphertext_b64>';
