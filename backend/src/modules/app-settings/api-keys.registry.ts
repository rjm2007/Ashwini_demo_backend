/**
 * The fixed set of credentials the admin "API Keys" screen can manage.
 *
 * Deliberately a closed allow-list rather than free-form key/value editing:
 * the endpoint writes to a table other services read, so an admin must not be
 * able to invent arbitrary setting names or overwrite unrelated config.
 */

export interface ApiKeyDefinition {
  /** Primary key in app_settings, and the id used by the HTTP API. */
  key: string;
  /** Env var consulted when no database value is set. */
  envVar: string;
  label: string;
  /** Shown under the field in the UI. */
  help: string;
  /** Secrets are masked on read; non-secrets are returned in full. */
  isSecret: boolean;
  /**
   * True when a saved value is picked up on the next request with no restart.
   * False means the consuming service reads it at process start (currently
   * only ai-service, which builds its OpenAI clients at import time), so the
   * UI has to say so instead of implying an immediate effect.
   */
  appliesLive: boolean;
  /** Whether this key can be verified against the provider. */
  testable: boolean;
}

export const API_KEY_DEFINITIONS: ApiKeyDefinition[] = [
  {
    key: "OPENAI_API_KEY",
    envVar: "OPENAI_API_KEY",
    label: "OpenAI API key",
    help: "Used by the AI service for extraction, embeddings, reranking and chat. The AI service reads this at startup, so a saved key applies after the ai-service container restarts.",
    isSecret: true,
    appliesLive: false,
    testable: true
  },
  {
    key: "VAPI_PRIVATE_KEY",
    envVar: "VAPI_PRIVATE_KEY",
    label: "Vapi private key",
    help: "Server-side key used to read and update voice agent system prompts. Applies immediately.",
    isSecret: true,
    appliesLive: true,
    testable: true
  },
  {
    key: "VAPI_PUBLIC_KEY",
    envVar: "VAPI_PUBLIC_KEY",
    label: "Vapi public key",
    help: "Browser key used to start voice calls from the Call page. Not a secret — it is delivered to the browser by design. Applies immediately.",
    isSecret: false,
    appliesLive: true,
    testable: false
  }
];

export function findApiKeyDefinition(key: string): ApiKeyDefinition | undefined {
  return API_KEY_DEFINITIONS.find((d) => d.key === key);
}
