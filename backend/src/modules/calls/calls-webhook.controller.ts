import { Body, Controller, ForbiddenException, Headers, Logger, Post } from "@nestjs/common";
import { CallsService } from "./calls.service";

/**
 * Public endpoint — Vapi posts here directly, so it CANNOT carry our JWT.
 * Excluded from AuthMiddleware in app.module.ts. Authenticity is verified
 * with the plain-string `x-vapi-secret` header, which Vapi sends whenever
 * the assistant's `server.secret` is configured (see the one-time Vapi
 * setup in Changes.md section 1 — that value must match VAPI_WEBHOOK_SECRET).
 */
@Controller("calls")
export class CallsWebhookController {
  private readonly logger = new Logger(CallsWebhookController.name);

  constructor(private readonly callsService: CallsService) {}

  @Post("webhook")
  async handleWebhook(@Body() body: any, @Headers("x-vapi-secret") secret: string) {
    const expected = process.env.VAPI_WEBHOOK_SECRET?.trim();
    if (!expected || secret !== expected) {
      this.logger.warn("Rejected Vapi webhook with invalid or missing x-vapi-secret");
      throw new ForbiddenException("Invalid webhook secret");
    }

    const message = body?.message;
    this.logger.debug(`Vapi webhook received type=${message?.type}`);

    if (!message || message.type !== "end-of-call-report") {
      // Vapi can be configured to send other event types too — acknowledge
      // anything we don't act on so Vapi doesn't retry forever.
      return { received: true, handled: false };
    }

    const call = message.call || {};
    const artifact = message.artifact || {};
    const vapiCallId: string | undefined = call.id;
    if (!vapiCallId) {
      this.logger.warn("end-of-call-report missing call.id — cannot persist");
      return { received: true, handled: false };
    }

    // assistantOverrides.metadata set by the frontend at call start (see
    // call/page.tsx) is expected to be echoed back on the call object.
    // Documentation on the exact nesting is inconsistent across Vapi's own
    // docs, so both plausible locations are checked defensively.
    const metadata = call.assistantOverrides?.metadata || call.metadata || {};
    const agentKey = metadata.agentKey || "unknown";
    const agentName = metadata.agentName;

    await this.callsService.completeCall({
      vapiCallId,
      agentKey,
      agentName,
      transcript: artifact.transcript || "",
      transcriptMessages: artifact.messages || [],
      endedReason: message.endedReason,
      endedAt: message.timestamp ? new Date(message.timestamp) : new Date()
    });

    return { received: true, handled: true };
  }
}
