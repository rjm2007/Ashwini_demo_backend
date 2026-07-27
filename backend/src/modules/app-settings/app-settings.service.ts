import { BadRequestException, Injectable, Logger, NotFoundException } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import { AppSettingEntity } from "./entities/app-setting.entity";
import { decryptSecret, encryptSecret, maskSecret } from "./crypto.util";
import { API_KEY_DEFINITIONS, ApiKeyDefinition, findApiKeyDefinition } from "./api-keys.registry";

export interface ApiKeyStatus {
  key: string;
  label: string;
  help: string;
  isSecret: boolean;
  appliesLive: boolean;
  testable: boolean;
  /** True when a value is available from either the database or the environment. */
  configured: boolean;
  /** "database" when an admin saved it here, "environment" when it falls back to .env. */
  source: "database" | "environment" | "none";
  /** Masked for secrets, full value for non-secrets, empty when unset. */
  preview: string;
  updatedAt: string | null;
}

@Injectable()
export class AppSettingsService {
  private readonly logger = new Logger(AppSettingsService.name);

  constructor(
    @InjectRepository(AppSettingEntity)
    private readonly repo: Repository<AppSettingEntity>
  ) {}

  /**
   * Resolves a managed credential: a value saved through the admin UI wins,
   * otherwise the process environment. This is the function other modules
   * should call instead of reading process.env directly.
   *
   * Never throws on a bad envelope — a credential that cannot be decrypted
   * (for example after the signing secret was rotated) falls back to the
   * environment and logs, rather than taking the whole feature down.
   */
  async resolve(key: string): Promise<string> {
    const definition = findApiKeyDefinition(key);
    const envValue = (definition ? process.env[definition.envVar] : process.env[key])?.trim() || "";

    let row: AppSettingEntity | null = null;
    try {
      row = await this.repo.findOne({ where: { settingKey: key } });
    } catch (err: any) {
      // Table missing (migration not applied yet) must not break callers.
      this.logger.warn(`Could not read app_settings for "${key}": ${err?.message ?? err}`);
      return envValue;
    }
    if (!row) return envValue;

    try {
      const value = decryptSecret(row.encryptedValue).trim();
      return value || envValue;
    } catch (err: any) {
      this.logger.error(
        `Stored value for "${key}" could not be decrypted (${err?.message ?? err}). ` +
          `Falling back to the environment. Re-enter this key in Settings > API Keys.`
      );
      return envValue;
    }
  }

  /** Status of every managed key, for the admin screen. Never returns a usable secret. */
  async listStatuses(): Promise<ApiKeyStatus[]> {
    let rows: AppSettingEntity[] = [];
    try {
      rows = await this.repo.find();
    } catch (err: any) {
      // Most likely app_settings does not exist because migration 009 has not
      // been applied. Degrade to showing the environment-sourced values rather
      // than 500-ing the whole screen — saving will still surface the real error.
      this.logger.warn(
        `Could not read app_settings (${err?.message ?? err}). ` +
          `Showing environment values only — has migration 009 been applied?`
      );
    }
    const byKey = new Map(rows.map((r) => [r.settingKey, r]));

    return API_KEY_DEFINITIONS.map((definition) => this.toStatus(definition, byKey.get(definition.key)));
  }

  private toStatus(definition: ApiKeyDefinition, row?: AppSettingEntity): ApiKeyStatus {
    const envValue = (process.env[definition.envVar] || "").trim();

    let dbValue = "";
    if (row) {
      try {
        dbValue = decryptSecret(row.encryptedValue).trim();
      } catch {
        // Undecryptable rows are reported as if unset so the admin re-enters them.
        dbValue = "";
      }
    }

    const effective = dbValue || envValue;
    const source: ApiKeyStatus["source"] = dbValue ? "database" : envValue ? "environment" : "none";

    return {
      key: definition.key,
      label: definition.label,
      help: definition.help,
      isSecret: definition.isSecret,
      appliesLive: definition.appliesLive,
      testable: definition.testable,
      configured: Boolean(effective),
      source,
      preview: effective ? (definition.isSecret ? maskSecret(effective) : effective) : "",
      updatedAt: dbValue && row ? row.updatedAt?.toISOString() ?? null : null
    };
  }

  async setKey(key: string, rawValue: string, userId?: string): Promise<ApiKeyStatus> {
    const definition = this.requireDefinition(key);
    const value = (rawValue || "").trim();
    if (!value) {
      throw new BadRequestException(`${definition.label} cannot be empty. Use delete to clear it.`);
    }

    await this.repo.save(
      this.repo.create({
        settingKey: definition.key,
        encryptedValue: encryptSecret(value),
        isSecret: definition.isSecret,
        updatedBy: userId ?? null
      })
    );
    this.logger.log(`API key "${definition.key}" updated by user ${userId ?? "unknown"}`);

    const row = await this.repo.findOne({ where: { settingKey: definition.key } });
    return this.toStatus(definition, row ?? undefined);
  }

  /** Removes the database override so the key falls back to the environment. */
  async clearKey(key: string): Promise<ApiKeyStatus> {
    const definition = this.requireDefinition(key);
    await this.repo.delete({ settingKey: definition.key });
    this.logger.log(`API key "${definition.key}" cleared; reverting to environment value.`);
    return this.toStatus(definition, undefined);
  }

  /**
   * Verifies a key against its provider. Tests the supplied candidate when one
   * is given (so an admin can check a key before saving it), otherwise the
   * currently resolved value.
   */
  async testKey(key: string, candidate?: string): Promise<{ ok: boolean; message: string }> {
    const definition = this.requireDefinition(key);
    if (!definition.testable) {
      throw new BadRequestException(`${definition.label} cannot be verified automatically.`);
    }

    const value = (candidate || "").trim() || (await this.resolve(definition.key));
    if (!value) {
      return { ok: false, message: `No ${definition.label} is configured.` };
    }

    switch (definition.key) {
      case "OPENAI_API_KEY":
        return this.probe("https://api.openai.com/v1/models", value, "OpenAI");
      case "VAPI_PRIVATE_KEY":
        return this.probe("https://api.vapi.ai/assistant?limit=1", value, "Vapi");
      default:
        throw new BadRequestException(`No verification is implemented for ${definition.label}.`);
    }
  }

  private async probe(url: string, token: string, provider: string): Promise<{ ok: boolean; message: string }> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal
      });
      if (response.ok) {
        return { ok: true, message: `${provider} accepted this key.` };
      }
      if (response.status === 401 || response.status === 403) {
        return { ok: false, message: `${provider} rejected this key (${response.status}).` };
      }
      return {
        ok: false,
        message: `${provider} returned an unexpected status (${response.status}). The key may still be valid.`
      };
    } catch (err: any) {
      const reason = err?.name === "AbortError" ? "the request timed out" : err?.message || "unknown error";
      return { ok: false, message: `Could not reach ${provider}: ${reason}.` };
    } finally {
      clearTimeout(timeout);
    }
  }

  private requireDefinition(key: string): ApiKeyDefinition {
    const definition = findApiKeyDefinition(key);
    if (!definition) {
      throw new NotFoundException(`"${key}" is not a manageable API key.`);
    }
    return definition;
  }
}
