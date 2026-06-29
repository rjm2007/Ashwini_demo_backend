-- 006_warranty_type_hardening.sql
-- Round 4: remove the column-level default so the app's explicit
-- declare-at-certify logic is the only source of truth for warranty_type.
-- Safe to run even if the default was never set (no-op, doesn't error).
ALTER TABLE documents ALTER COLUMN warranty_type DROP DEFAULT;
