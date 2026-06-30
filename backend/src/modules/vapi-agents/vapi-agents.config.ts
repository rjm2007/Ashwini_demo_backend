export interface VapiAgentConfig {
  key: string;
  name: string;
  assistantId: string;
}

/**
 * Small, static, env-driven registry of named Vapi agents. Not a database
 * table by design — this is a fixed, named set (Ashwini / Rohini), not a
 * general admin CRUD feature. Adding a third agent later means one more
 * env var pair plus one more entry here.
 */
export function getVapiAgents(): VapiAgentConfig[] {
  const agents: VapiAgentConfig[] = [];

  if (process.env.VAPI_AGENT_ASHWINI_ID) {
    agents.push({
      key: "ashwini",
      name: process.env.VAPI_AGENT_ASHWINI_NAME || "Ashwini Agent",
      assistantId: process.env.VAPI_AGENT_ASHWINI_ID
    });
  }
  if (process.env.VAPI_AGENT_ROHINI_ID) {
    agents.push({
      key: "rohini",
      name: process.env.VAPI_AGENT_ROHINI_NAME || "Rohini Agent",
      assistantId: process.env.VAPI_AGENT_ROHINI_ID
    });
  }
  return agents;
}

export function getVapiAgentByKey(key: string): VapiAgentConfig | undefined {
  return getVapiAgents().find((a) => a.key === key);
}
