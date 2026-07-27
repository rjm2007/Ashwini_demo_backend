-- 008_rename_voice_agents.sql
-- Renames the two voice agents: ashwini -> david, rohini -> raechal.
--
-- This touches three things:
--   1. agent_prompts.agent_key  (primary key)
--   2. call_logs.agent_key      (plain column, no FK, so it is remapped by hand)
--   3. the system prompt text itself, which literally says "You are Ashwini,"
--      / "You are Rohini," — without this the voice agent keeps introducing
--      itself by the old name on live calls, which is the whole point of the
--      rename.
--
-- Idempotent: safe to run more than once, and safe on a fresh database where
-- 007 has just seeded the old keys.
\set ON_ERROR_STOP on

BEGIN;

-- 1. agent_prompts. If a row for the new key somehow already exists, keep it
--    and drop the stale old-key row rather than failing on the primary key.
UPDATE agent_prompts
   SET agent_key = 'david'
 WHERE agent_key = 'ashwini'
   AND NOT EXISTS (SELECT 1 FROM agent_prompts WHERE agent_key = 'david');
DELETE FROM agent_prompts WHERE agent_key = 'ashwini';

UPDATE agent_prompts
   SET agent_key = 'raechal'
 WHERE agent_key = 'rohini'
   AND NOT EXISTS (SELECT 1 FROM agent_prompts WHERE agent_key = 'raechal');
DELETE FROM agent_prompts WHERE agent_key = 'rohini';

-- 2. call_logs keeps its historical rows; only the key label is remapped so
--    old calls still resolve to the agent they were actually handled by.
UPDATE call_logs SET agent_key = 'david'   WHERE agent_key = 'ashwini';
UPDATE call_logs SET agent_key = 'raechal' WHERE agent_key = 'rohini';

UPDATE call_logs SET agent_name = 'David Agent'   WHERE agent_name = 'Ashwini Agent';
UPDATE call_logs SET agent_name = 'Raechal Agent' WHERE agent_name = 'Rohini Agent';

-- 3. Prompt text. Replace the persona name wherever it appears. The prompts
--    refer to the agent by bare first name ("You are Ashwini,", "you are
--    Ashwini from fleet support"), so a plain replace of the word is correct
--    and there is no other legitimate use of these words in the prompts.
UPDATE agent_prompts
   SET prompt = replace(prompt, 'Ashwini', 'David')
 WHERE agent_key = 'david' AND prompt LIKE '%Ashwini%';

UPDATE agent_prompts
   SET prompt = replace(prompt, 'Rohini', 'Raechal')
 WHERE agent_key = 'raechal' AND prompt LIKE '%Rohini%';

COMMIT;
