import { Injectable, Logger, NotFoundException } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import { QuerySessionEntity } from "./entities/query-session.entity";
import { QueryMessageEntity, QueryMessageRole } from "./entities/query-message.entity";

@Injectable()
export class QueryService {
  private readonly logger = new Logger(QueryService.name);

  constructor(
    @InjectRepository(QuerySessionEntity)
    private readonly sessionRepository: Repository<QuerySessionEntity>,
    @InjectRepository(QueryMessageEntity)
    private readonly messageRepository: Repository<QueryMessageEntity>
  ) {}

  async createSession(userId: string, title?: string) {
    // This function creates a new query chat session for the current user.
    const session = this.sessionRepository.create({
      userId,
      title: title || "New Chat",
      lastMessageAt: new Date()
    });
    return this.sessionRepository.save(session);
  }

  async listSessions(userId: string) {
    // This function lists all sessions for the user ordered by latest activity.
    return this.sessionRepository.find({ where: { userId }, order: { lastMessageAt: "DESC" } });
  }

  async getSession(sessionId: string, userId: string) {
    // This function returns one session and all its messages.
    const session = await this.sessionRepository.findOne({ where: { id: sessionId, userId } });
    if (!session) {
      throw new NotFoundException("Session not found");
    }
    const messages = await this.messageRepository.find({
      where: { sessionId },
      order: { createdAt: "ASC" }
    });
    return { ...session, messages };
  }

  async deleteSession(sessionId: string, userId: string) {
    // This function deletes a session owned by the current user.
    const session = await this.sessionRepository.findOne({ where: { id: sessionId, userId } });
    if (!session) {
      throw new NotFoundException("Session not found");
    }
    await this.sessionRepository.delete(session.id);
    return { success: true };
  }

  async sendMessage(
    sessionId: string,
    userId: string,
    content: string,
    documentId?: string,
    context?: Record<string, unknown>
  ) {
    // This function stores user message, calls AI answer API, and stores assistant response.
    const session = await this.sessionRepository.findOne({ where: { id: sessionId, userId } });
    if (!session) {
      throw new NotFoundException("Session not found");
    }
    const previousUserMessageCount = await this.messageRepository.count({
      where: { sessionId, role: QueryMessageRole.USER }
    });

    const userMessage = this.messageRepository.create({
      sessionId,
      role: QueryMessageRole.USER,
      content
    });
    await this.messageRepository.save(userMessage);

    const history = await this.messageRepository.find({
      where: { sessionId },
      order: { createdAt: "ASC" },
      take: 12
    });

    const aiUrl = `${process.env.AI_SERVICE_URL}/query/answer`;
    this.logger.log(`sendMessage -> AI ${aiUrl} sessionId=${sessionId}`);

    let httpResponse: Response | undefined;
    let networkError: any;
    try {
      httpResponse = await fetch(aiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: content,
          conversationHistory: history.map((item) => ({ role: item.role, content: item.content })),
          documentId: documentId || undefined,
          sessionId,
          context: context || undefined
        })
      });
    } catch (err: any) {
      networkError = err;
      this.logger.error(`AI service unreachable url=${aiUrl} error=${err?.message ?? err}`);
    }

    let aiResponse: any = {};
    let rawText = "";
    let status = 0;
    if (httpResponse) {
      status = httpResponse.status;
      rawText = await httpResponse.text();
      if (httpResponse.ok) {
        try {
          aiResponse = JSON.parse(rawText);
        } catch (err: any) {
          this.logger.error(
            `AI returned 200 but body was not JSON. body=${rawText.slice(0, 200)} err=${err?.message ?? err}`
          );
        }
      } else {
        this.logger.error(
          `AI service answer failed status=${status} body=${rawText.slice(0, 500)}`
        );
      }
    }
    this.logger.log(
      `AI answer status=${status} reachable=${Boolean(httpResponse)} answerChars=${(aiResponse?.answer ?? "").length} evidence=${(aiResponse?.evidence ?? []).length}`
    );

    let assistantContent: string;
    if (aiResponse.answer) {
      assistantContent = aiResponse.answer;
    } else if (!httpResponse) {
      assistantContent = "Could not reach the AI service. Please try again in a moment.";
    } else if (!httpResponse.ok) {
      assistantContent = `AI service error (status ${status}). Please try again.`;
    } else {
      assistantContent = "I could not find enough certified evidence to answer this.";
    }

    const assistantMessage = this.messageRepository.create({
      sessionId,
      role: QueryMessageRole.ASSISTANT,
      content: assistantContent,
      confidenceScore: aiResponse.confidence || 0,
      evidenceJson: {
        evidence: aiResponse.evidence || [],
        responseType: aiResponse.responseType,
        decision: aiResponse.decision,
        coverageDecision: aiResponse.coverageDecision,
        explanation: aiResponse.explanation,
        matchedComponent: aiResponse.matchedComponent,
        durationMonths: aiResponse.durationMonths,
        mileageLimit: aiResponse.mileageLimit,
        mileageUnit: aiResponse.mileageUnit,
        checks: aiResponse.checks,
        exclusions: aiResponse.exclusions,
        conditions: aiResponse.conditions,
        limitOfLiability: aiResponse.limitOfLiability,
        deductible: aiResponse.deductible,
        planTier: aiResponse.planTier,
        candidates: aiResponse.candidates,
        fields: aiResponse.fields,
        coverages: aiResponse.coverages,
        turnCostUsd: aiResponse.turnCostUsd
      },
      metadataFiltersAppliedJson: {
        ...(aiResponse.filters || {}),
        context: aiResponse.context || context || {},
        cost: aiResponse.cost || undefined
      }
    });
    await this.messageRepository.save(assistantMessage);

    if (
      previousUserMessageCount === 0 &&
      (session.title === "New Chat" || session.title === "New Warranty Session")
    ) {
      const title = content
        .replace(/\s+/g, " ")
        .trim()
        .split(" ")
        .slice(0, 7)
        .join(" ");
      session.title = title.length > 0 ? title : "New Chat";
    }
    session.lastMessageAt = new Date();
    await this.sessionRepository.save(session);

    return assistantMessage;
  }
}
