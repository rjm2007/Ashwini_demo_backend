import { createCipheriv, createDecipheriv, randomBytes, scryptSync } from "crypto";

/**
 * AES-256-GCM envelope encryption for values held in `app_settings`.
 *
 * Provider credentials entered through the admin UI are written to Postgres,
 * so they must not sit there in plaintext — a database dump would otherwise
 * hand over the OpenAI and Vapi keys directly.
 *
 * The data key is derived with scrypt from SETTINGS_ENCRYPTION_KEY, falling
 * back to JWT_SECRET so an existing deployment does not need a new secret
 * before this feature works. Rotating either value makes previously stored
 * ciphertexts undecryptable by design — decrypt() reports that as a clear
 * error rather than returning garbage, and the admin simply re-enters the key.
 */

const ENVELOPE_VERSION = "v1";
const ALGORITHM = "aes-256-gcm";
const IV_BYTES = 12; // 96-bit nonce, the size GCM is specified for
const KEY_BYTES = 32;

// Fixed salt: the derived key must be stable across restarts and across the
// backend's replicas, otherwise previously stored values stop decrypting. The
// salt is not the secret here — SETTINGS_ENCRYPTION_KEY / JWT_SECRET is.
const KEY_SALT = "warranty-platform/app-settings/v1";

let cachedKey: Buffer | null = null;
let cachedSecret: string | null = null;

function getKey(): Buffer {
  const secret = (process.env.SETTINGS_ENCRYPTION_KEY || process.env.JWT_SECRET || "").trim();
  if (!secret) {
    throw new Error(
      "Cannot encrypt settings: neither SETTINGS_ENCRYPTION_KEY nor JWT_SECRET is set on the server."
    );
  }
  // Re-derive if the secret changed under us (e.g. env reloaded in dev).
  if (!cachedKey || cachedSecret !== secret) {
    cachedKey = scryptSync(secret, KEY_SALT, KEY_BYTES);
    cachedSecret = secret;
  }
  return cachedKey;
}

export function encryptSecret(plaintext: string): string {
  const iv = randomBytes(IV_BYTES);
  const cipher = createCipheriv(ALGORITHM, getKey(), iv);
  const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const authTag = cipher.getAuthTag();
  return [
    ENVELOPE_VERSION,
    iv.toString("base64"),
    authTag.toString("base64"),
    ciphertext.toString("base64")
  ].join(":");
}

export function decryptSecret(envelope: string): string {
  const parts = (envelope || "").split(":");
  if (parts.length !== 4 || parts[0] !== ENVELOPE_VERSION) {
    throw new Error("Stored setting is not a recognised encrypted envelope.");
  }
  const [, ivB64, tagB64, dataB64] = parts;
  const decipher = createDecipheriv(ALGORITHM, getKey(), Buffer.from(ivB64, "base64"));
  decipher.setAuthTag(Buffer.from(tagB64, "base64"));
  return Buffer.concat([
    decipher.update(Buffer.from(dataB64, "base64")),
    decipher.final()
  ]).toString("utf8");
}

/**
 * Masks a credential for display: enough leading/trailing characters to
 * recognise which key is installed, never enough to use it. Short values are
 * fully masked rather than partially revealed.
 */
export function maskSecret(plaintext: string): string {
  const value = plaintext || "";
  if (value.length <= 12) return "•".repeat(Math.max(value.length, 4));
  return `${value.slice(0, 6)}…${value.slice(-4)}`;
}
