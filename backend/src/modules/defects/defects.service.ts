import { BadRequestException, Injectable, Logger, NotFoundException } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import { DefectEntity } from "./entities/defect.entity";
import { DefectMessageEntity, DefectMessageRole } from "./entities/defect-message.entity";
import { DocumentEntity } from "../documents/entities/document.entity";
import { DocumentRepository } from "../documents/entities/document-status.enum";
import { CreateDefectDto } from "./dto/create-defect.dto";

const AI_SERVICE_URL = process.env.AI_SERVICE_URL || "http://localhost:8000";

@Injectable()
export class DefectsService {
  private readonly logger = new Logger(DefectsService.name);

  constructor(
    @InjectRepository(DefectEntity)
    private readonly defectsRepo: Repository<DefectEntity>,
    @InjectRepository(DefectMessageEntity)
    private readonly messagesRepo: Repository<DefectMessageEntity>,
    @InjectRepository(DocumentEntity)
    private readonly documentsRepo: Repository<DocumentEntity>
  ) {}

  private normalizeMakeForGrouping(make?: string | null): string {
    return (make || "").trim().toLowerCase().replace(/\btruck\b/g, "").replace(/\s+/g, " ").trim();
  }
  private normalizeModelForGrouping(model?: string | null): string {
    return (model || "").trim().toLowerCase().replace(/\s+/g, "");
  }

  /** One entry per UNIQUE Make+Model+Year, each carrying the list of specific
   *  vehicles (documents/VINs) behind it. The dropdown shows the group once;
   *  a second selector only appears client-side when vehicles.length > 1. */
  async listEligibleDocuments() {
    const docs = await this.documentsRepo.find({
      where: { currentRepository: DocumentRepository.CERTIFIED },
      order: { uploadedAt: "DESC" }
    });
    const eligible = docs.filter((d) => d.make && d.model);

    const groups = new Map<
      string,
      {
        make: string;
        model: string;
        year: number | null;
        vehicles: Array<{
          documentId: string;
          originalFilename: string;
          warrantyType: string;
          vinSuffix: string | null;
        }>;
      }
    >();

    for (const d of eligible) {
      const key = `${this.normalizeMakeForGrouping(d.make)}|${this.normalizeModelForGrouping(d.model)}|${
        d.year ?? ""
      }`;
      const meta = (d.metadataJson as Record<string, any>) || {};
      const schema = (d.masterSchemaJson as Record<string, any>) || {};
      const vehicle = schema.vehicle || {};
      const vin = meta.vin || vehicle.vin?.value || null;
      const chassis = meta.chassis_id || vehicle.chassis_id?.value || null;
      const identifier = vin || chassis || null;

      if (!groups.has(key)) {
        groups.set(key, { make: d.make as string, model: d.model as string, year: d.year ?? null, vehicles: [] });
      }
      groups.get(key)!.vehicles.push({
        documentId: d.id,
        originalFilename: d.originalFilename,
        warrantyType: d.warrantyType || "standard",
        vinSuffix: identifier ? String(identifier).slice(-6) : null
      });
    }

    return Array.from(groups.values());
  }

  private async callAi(
    question: string,
    documentId: string,
    context: Record<string, unknown>,
    conversationHistory: Array<{ role: string; content: string }>
  ): Promise<any> {
    let httpResponse: Response | undefined;
    try {
      httpResponse = await fetch(`${AI_SERVICE_URL}/defect/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, documentId, context, conversationHistory })
      });
    } catch (err: any) {
      this.logger.error(`AI defect service unreachable: ${err?.message ?? err}`);
      throw new BadRequestException("Could not reach the AI service. Please try again.");
    }
    if (!httpResponse.ok) {
      const body = await httpResponse.text().catch(() => "");
      this.logger.error(`AI defect service error status=${httpResponse.status} body=${body.slice(0, 300)}`);
      throw new BadRequestException(`AI service error (status ${httpResponse.status}).`);
    }
    try {
      return JSON.parse(await httpResponse.text());
    } catch {
      throw new BadRequestException("AI service returned an unreadable response.");
    }
  }

  /** Creates the defect AND immediately produces the first verdict — no second round-trip needed. */
  async create(createDto: CreateDefectDto, userId: string) {
    const document = await this.documentsRepo.findOne({ where: { id: createDto.documentId } });
    if (!document) {
      throw new NotFoundException("Document not found");
    }
    if (document.currentRepository !== DocumentRepository.CERTIFIED) {
      throw new BadRequestException("Document must be certified before reporting a defect against it");
    }

    const context = {
      eligibility: {
        purchase_date: createDto.purchaseDate,
        current_mileage: createDto.currentMileage
      }
    };

    const aiResponse = await this.callAi(createDto.reportedDefect, createDto.documentId, context, []);

    const defect = this.defectsRepo.create({
      documentId: createDto.documentId,
      reportedDefect: createDto.reportedDefect,
      purchaseDate: createDto.purchaseDate,
      currentMileage: createDto.currentMileage,
      createdBy: userId,
      make: document.make,
      model: document.model,
      year: document.year,
      warrantyType: document.warrantyType,
      primaryDecision: aiResponse.primary_decision || aiResponse.coverageDecision,
      primaryComponent: aiResponse.clause_results?.[0]?.warranty_heading,
      primaryCoverageId: aiResponse.clause_results?.[0]?.coverage_id,
      overallConfidenceScore: aiResponse.overall_confidence_score ?? aiResponse.confidence,
      contextJson: aiResponse.context || context
    });
    const saved = await this.defectsRepo.save(defect);

    const userMessage = await this.messagesRepo.save(
      this.messagesRepo.create({
        defectId: saved.id,
        role: DefectMessageRole.USER,
        content: createDto.reportedDefect
      })
    );
    const assistantMessage = await this.messagesRepo.save(
      this.messagesRepo.create({
        defectId: saved.id,
        role: DefectMessageRole.ASSISTANT,
        content: aiResponse.user_message || aiResponse.answer || "No answer generated.",
        evidenceJson: aiResponse,
        confidenceScore: aiResponse.overall_confidence_score ?? aiResponse.confidence
      })
    );

    return { ...saved, messages: [userMessage, assistantMessage] };
  }

  /** Scoped to the caller — no longer leaks every user's defects. */
  async findAll(userId: string): Promise<DefectEntity[]> {
    return this.defectsRepo.find({
      where: { createdBy: userId },
      order: { createdAt: "DESC" }
    });
  }

  /** Now actually returns the conversation, not a bare row. */
  async findOne(id: string, userId: string) {
    const defect = await this.defectsRepo.findOne({ where: { id, createdBy: userId } });
    if (!defect) {
      throw new NotFoundException(`Defect with id ${id} not found`);
    }
    const messages = await this.messagesRepo.find({
      where: { defectId: id },
      order: { createdAt: "ASC" }
    });
    return { ...defect, messages };
  }

  async addMessage(defectId: string, content: string, userId: string) {
    const defect = await this.defectsRepo.findOne({ where: { id: defectId, createdBy: userId } });
    if (!defect) {
      throw new NotFoundException(`Defect with id ${defectId} not found`);
    }

    await this.messagesRepo.save(
      this.messagesRepo.create({ defectId, role: DefectMessageRole.USER, content })
    );

    const priorMessages = await this.messagesRepo.find({
      where: { defectId },
      order: { createdAt: "ASC" }
    });
    const conversationHistory = priorMessages.map((m) => ({
      role: String(m.role).toLowerCase(),
      content: m.content
    }));

    const aiResponse = await this.callAi(content, defect.documentId, defect.contextJson || {}, conversationHistory);

    const assistantMessage = await this.messagesRepo.save(
      this.messagesRepo.create({
        defectId,
        role: DefectMessageRole.ASSISTANT,
        content: aiResponse.user_message || aiResponse.answer || "No answer generated.",
        evidenceJson: aiResponse,
        confidenceScore: aiResponse.overall_confidence_score ?? aiResponse.confidence
      })
    );

    defect.contextJson = aiResponse.context || defect.contextJson;
    if (aiResponse.primary_decision) defect.primaryDecision = aiResponse.primary_decision;
    if (aiResponse.clause_results?.[0]) {
      defect.primaryComponent = aiResponse.clause_results[0].warranty_heading;
      defect.primaryCoverageId = aiResponse.clause_results[0].coverage_id;
    }
    await this.defectsRepo.save(defect);

    return assistantMessage;
  }

  async transcribeVoiceToEnglish(file: Express.Multer.File): Promise<{ text: string }> {
    const form = new FormData();
    form.append("file", new Blob([file.buffer as any], { type: file.mimetype }), file.originalname || "audio.webm");

    let res: Response;
    try {
      res = await fetch(`${AI_SERVICE_URL}/voice/translate`, { method: "POST", body: form });
    } catch (err: any) {
      this.logger.error(`voice translate unreachable: ${err?.message ?? err}`);
      throw new BadRequestException("Could not reach the voice transcription service.");
    }
    if (!res.ok) {
      throw new BadRequestException(`Voice transcription failed (status ${res.status}).`);
    }
    return res.json();
  }
}
