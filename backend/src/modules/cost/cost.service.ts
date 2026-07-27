import { Injectable, Logger } from "@nestjs/common";

const COST_FETCH_TIMEOUT_MS = 25000;

/**
 * Thin proxy to the AI service, which owns the cost_events table.
 *
 * An unreachable AI service used to be reported as a genuine zero, so the UI
 * confidently showed "$0.00" when it actually knew nothing. Failures now carry
 * `unavailable: true` so callers can say "couldn't load" instead of lying, and
 * they are logged rather than swallowed. A missing timeout also meant one hung
 * AI service could pin a request open indefinitely.
 */
@Injectable()
export class CostService {
  private readonly logger = new Logger(CostService.name);

  private aiBase() {
    return process.env.AI_SERVICE_URL || "http://ai-service:8000";
  }

  private async fetchJson(path: string, fallback: Record<string, unknown>) {
    const controller = new AbortController();
    // Generous on purpose: the AI service's FIRST request after a restart takes
    // ~15s to warm up (connection pool + heavy imports), while every subsequent
    // one is single-digit milliseconds. A tighter timeout turned that one cold
    // start into a false "AI service unreachable" on the dashboard.
    const timeout = setTimeout(() => controller.abort(), COST_FETCH_TIMEOUT_MS);
    try {
      const res = await fetch(`${this.aiBase()}${path}`, { signal: controller.signal });
      if (!res.ok) {
        this.logger.warn(`AI service returned ${res.status} for ${path}`);
        return { ...fallback, unavailable: true };
      }
      return await res.json();
    } catch (err: any) {
      const reason = err?.name === "AbortError" ? "timed out" : err?.message || "unknown error";
      this.logger.warn(`Could not reach AI service for ${path}: ${reason}`);
      return { ...fallback, unavailable: true };
    } finally {
      clearTimeout(timeout);
    }
  }

  async getDocumentCost(documentId: string) {
    return this.fetchJson(`/cost/document/${documentId}`, {
      documentId,
      totalUsd: 0,
      breakdown: []
    });
  }

  async getSessionCost(sessionId: string) {
    return this.fetchJson(`/cost/session/${sessionId}`, { sessionId, totalUsd: 0 });
  }

  async getDailyCost() {
    return this.fetchJson(`/cost/daily`, {
      today_usd: 0,
      month_usd: 0,
      avg_per_query_usd: 0,
      by_stage: {}
    });
  }
}
