import { Injectable } from "@nestjs/common";

@Injectable()
export class CostService {
  private aiBase() {
    return process.env.AI_SERVICE_URL || "http://ai-service:8000";
  }

  async getDocumentCost(documentId: string) {
    const res = await fetch(`${this.aiBase()}/cost/document/${documentId}`);
    if (!res.ok) {
      return { documentId, totalUsd: 0, breakdown: [] };
    }
    return res.json();
  }

  async getSessionCost(sessionId: string) {
    const res = await fetch(`${this.aiBase()}/cost/session/${sessionId}`);
    if (!res.ok) {
      return { sessionId, totalUsd: 0 };
    }
    return res.json();
  }

  async getDailyCost() {
    const res = await fetch(`${this.aiBase()}/cost/daily`);
    if (!res.ok) {
      return { totalUsd: 0, byStage: {} };
    }
    return res.json();
  }
}
