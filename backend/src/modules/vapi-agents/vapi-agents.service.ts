import { BadRequestException, Injectable, Logger, NotFoundException } from "@nestjs/common";
import { VapiClient } from "@vapi-ai/server-sdk";
import { getVapiAgentByKey, getVapiAgents, VapiAgentConfig } from "./vapi-agents.config";

@Injectable()
export class VapiAgentsService {
  private readonly logger = new Logger(VapiAgentsService.name);

  private getClient(): VapiClient {
    const token = process.env.VAPI_PRIVATE_KEY;
    if (!token) {
      throw new BadRequestException("VAPI_PRIVATE_KEY is not configured on the server.");
    }
    return new VapiClient({ token });
  }

  private requireAgent(key: string): VapiAgentConfig {
    const agent = getVapiAgentByKey(key);
    if (!agent) {
      throw new NotFoundException(
        `Unknown or unconfigured agent "${key}". Check that its assistant ID env var is set.`
      );
    }
    return agent;
  }

  /** List of agents available right now — only ones with a configured assistant ID. */
  listAgents() {
    return getVapiAgents().map(({ key, name, assistantId }) => ({ key, name, assistantId }));
  }

  /** Reads the assistant's CURRENT system prompt from its live Vapi config. */
  async getSystemPrompt(key: string): Promise<{ prompt: string }> {
    const agent = this.requireAgent(key);
    const client = this.getClient();

    let assistant: any;
    try {
      assistant = await client.assistants.get(agent.assistantId as any);
    } catch (err: any) {
      this.logger.error(`Failed to fetch Vapi assistant ${agent.assistantId}: ${err?.message ?? err}`);
      throw new BadRequestException("Could not reach Vapi to read this agent's configuration.");
    }

    const messages: any[] = assistant?.model?.messages || [];
    const systemMessage = messages.find((m) => m.role === "system");
    return { prompt: systemMessage?.content || "" };
  }

  /**
   * Updates ONLY the system prompt text, without disturbing the assistant's
   * voice, transcriber, or other model settings (provider, model name,
   * temperature, tools, etc.).
   *
   * IMPORTANT: Vapi's PATCH /assistant/{id} replaces the nested `model`
   * object as a whole rather than deep-merging it. Sending a partial model
   * object (e.g. just { messages: [...] }) risks silently resetting the
   * provider/model/temperature/tools. To avoid that, this always reads the
   * assistant's CURRENT full model object first, mutates only the system
   * message's content inside it, and writes the entire model object back.
   * Do not "simplify" this into a direct partial PATCH.
   */
  async updateSystemPrompt(key: string, newPrompt: string): Promise<{ success: true }> {
    if (!newPrompt || !newPrompt.trim()) {
      throw new BadRequestException("System prompt cannot be empty.");
    }
    const agent = this.requireAgent(key);
    const client = this.getClient();

    let assistant: any;
    try {
      assistant = await client.assistants.get(agent.assistantId as any);
    } catch (err: any) {
      this.logger.error(`Failed to fetch Vapi assistant ${agent.assistantId}: ${err?.message ?? err}`);
      throw new BadRequestException("Could not reach Vapi to read this agent's current configuration.");
    }

    const currentModel = assistant?.model || {};
    const messages: any[] = Array.isArray(currentModel.messages) ? [...currentModel.messages] : [];
    const systemIndex = messages.findIndex((m) => m.role === "system");

    if (systemIndex >= 0) {
      messages[systemIndex] = { ...messages[systemIndex], content: newPrompt };
    } else {
      messages.unshift({ role: "system", content: newPrompt });
    }

    const updatedModel = { ...currentModel, messages };

    try {
      await client.assistants.update(agent.assistantId as any, { model: updatedModel } as any);
    } catch (err: any) {
      this.logger.error(`Failed to update Vapi assistant ${agent.assistantId}: ${err?.message ?? err}`);
      throw new BadRequestException(
        err?.message || "Could not update this agent's prompt on Vapi. The prompt was not saved."
      );
    }

    this.logger.log(`Updated system prompt for agent "${key}" (assistant ${agent.assistantId})`);
    return { success: true };
  }
}
