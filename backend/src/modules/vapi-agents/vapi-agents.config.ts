export interface VapiAgentConfig {
  key: string;
  name: string;
  assistantId: string;
}

/**
 * Small, static, env-driven registry of named Vapi agents. Not a database
 * table by design — this is a fixed, named set (David / Raechal), not a
 * general admin CRUD feature. Adding a third agent later means one more
 * env var pair plus one more entry here.
 *
 * These agents were previously keyed "ashwini" / "rohini". Migration 008
 * renamed the keys in agent_prompts and call_logs. The old
 * VAPI_AGENT_ASHWINI_ID / VAPI_AGENT_ROHINI_ID env vars are still accepted as
 * a fallback for the assistant ID (the underlying Vapi assistant UUID did not
 * change), so an environment whose .env has not been updated yet keeps working.
 *
 * The old *_NAME vars are deliberately NOT read as a fallback: they still hold
 * the retired "Ashwini Agent" / "Rohini Agent" strings, and honouring them
 * would put the old names straight back into the UI.
 */
export function getVapiAgents(): VapiAgentConfig[] {
  const agents: VapiAgentConfig[] = [];

  const davidId = (process.env.VAPI_AGENT_DAVID_ID || process.env.VAPI_AGENT_ASHWINI_ID)?.trim();
  if (davidId) {
    agents.push({
      key: "david",
      name: process.env.VAPI_AGENT_DAVID_NAME?.trim() || "David Agent",
      assistantId: davidId
    });
  }

  const raechalId = (process.env.VAPI_AGENT_RAECHAL_ID || process.env.VAPI_AGENT_ROHINI_ID)?.trim();
  if (raechalId) {
    agents.push({
      key: "raechal",
      name: process.env.VAPI_AGENT_RAECHAL_NAME?.trim() || "Raechal Agent",
      assistantId: raechalId
    });
  }
  return agents;
}

export function getVapiAgentByKey(key: string): VapiAgentConfig | undefined {
  return getVapiAgents().find((a) => a.key === key);
}
