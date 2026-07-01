import { Injectable, Logger, NotFoundException } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import { CallLogEntity, CallLogStatus } from "./entities/call-log.entity";
import { UserRole } from "../../common/enums/user-role.enum";

const AI_SERVICE_URL = process.env.AI_SERVICE_URL || "http://ai-service:8000";

@Injectable()
export class CallsService {
  private readonly logger = new Logger(CallsService.name);

  constructor(
    @InjectRepository(CallLogEntity)
    private readonly callLogsRepo: Repository<CallLogEntity>
  ) {}

  /** Called right when a call starts in the browser — creates the row the "View thread" link opens immediately. */
  async startCall(
    vapiCallId: string,
    agentKey: string,
    agentName: string | undefined,
    userId: string | undefined,
    userEmail: string | undefined
  ) {
    const existing = await this.callLogsRepo.findOne({ where: { vapiCallId } });
    if (existing) return existing;

    return this.callLogsRepo.save(
      this.callLogsRepo.create({
        vapiCallId,
        agentKey,
        agentName,
        createdBy: userId,
        createdByEmail: userEmail,
        status: CallLogStatus.IN_PROGRESS,
        startedAt: new Date()
      })
    );
  }

  async findAll(userId: string, role: string): Promise<CallLogEntity[]> {
    // Admins see every call for audit purposes; everyone else sees only their own calls.
    const where = role === UserRole.ADMIN ? {} : { createdBy: userId };
    return this.callLogsRepo.find({ where, order: { startedAt: "DESC" } });
  }

  async findOne(id: string, userId: string, role: string): Promise<CallLogEntity> {
    const callLog = await this.callLogsRepo.findOne({ where: { id } });
    if (!callLog) {
      throw new NotFoundException(`Call log with id ${id} not found`);
    }
    if (role !== UserRole.ADMIN && callLog.createdBy !== userId) {
      throw new NotFoundException(`Call log with id ${id} not found`);
    }
    return callLog;
  }

  /**
   * Called by CallsWebhookController when Vapi's end-of-call-report lands.
   * Looks up the row created at call-start by vapiCallId; if none exists
   * (e.g. the browser tab closed before the initial ping went out, or the
   * call didn't originate from our UI), creates one so no data is lost.
   */
  async completeCall(params: {
    vapiCallId: string;
    agentKey: string;
    agentName?: string;
    transcript: string;
    transcriptMessages: Record<string, unknown>[];
    endedReason?: string;
    endedAt?: Date;
  }): Promise<CallLogEntity> {
    let callLog = await this.callLogsRepo.findOne({ where: { vapiCallId: params.vapiCallId } });
    if (!callLog) {
      this.logger.warn(`No existing call_log row for vapiCallId=${params.vapiCallId}; backfilling.`);
      callLog = this.callLogsRepo.create({
        vapiCallId: params.vapiCallId,
        agentKey: params.agentKey,
        agentName: params.agentName,
        status: CallLogStatus.IN_PROGRESS,
        startedAt: new Date()
      });
    }

    callLog.transcript = params.transcript;
    callLog.transcriptMessagesJson = params.transcriptMessages;
    callLog.endedReason = params.endedReason;
    callLog.endedAt = params.endedAt || new Date();

    const summary = await this.summarizeViaAiService(
      params.transcript,
      params.agentKey,
      params.agentName || callLog.agentName || ""
    );
    callLog.eventDescription = summary.eventDescription;
    callLog.summary = summary.summary;
    callLog.recommendation = summary.recommendation;
    callLog.documentsCollected = summary.documentsCollected;
    callLog.documentsPending = summary.documentsPending;
    callLog.status = CallLogStatus.COMPLETED;

    return this.callLogsRepo.save(callLog);
  }

  private async summarizeViaAiService(transcript: string, agentKey: string, agentName: string) {
    try {
      const res = await fetch(`${AI_SERVICE_URL}/call/summarize`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript, agentKey, agentName })
      });
      if (!res.ok) {
        throw new Error(`ai-service responded ${res.status}`);
      }
      return await res.json();
    } catch (err: any) {
      this.logger.error(`call summarize failed: ${err?.message ?? err}`);
      return {
        eventDescription: "Call logged",
        summary: "Could not generate an AI summary for this call. The raw transcript is still available below.",
        recommendation: "Review the transcript manually.",
        documentsCollected: [],
        documentsPending: []
      };
    }
  }
}
