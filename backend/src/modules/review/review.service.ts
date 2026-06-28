import { BadRequestException, Injectable, Logger, NotFoundException } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { DataSource, In, Repository } from "typeorm";
import { UserRole } from "../../common/enums/user-role.enum";
import { DocumentsService } from "../documents/documents.service";
import { DocumentEntity } from "../documents/entities/document.entity";
import { DocumentRepository, ProcessingStatus } from "../documents/entities/document-status.enum";
import { ReviewEntity, ReviewFinalStatus } from "./entities/review.entity";
import { UpdateMetadataDto } from "./dto/update-metadata.dto";
import { S3Service } from "../documents/s3.service";

@Injectable()
export class ReviewService {
  private readonly logger = new Logger(ReviewService.name);

  constructor(
    @InjectRepository(ReviewEntity)
    private readonly reviewRepository: Repository<ReviewEntity>,
    @InjectRepository(DocumentEntity)
    private readonly documentsRepository: Repository<DocumentEntity>,
    private readonly documentsService: DocumentsService,
    private readonly s3Service: S3Service,
    private readonly dataSource: DataSource
  ) {}

  async getPendingDocuments(role: UserRole) {
    // Source of truth is the documents table: a doc enters the queue
    // as soon as the AI pipeline marks it ready_for_review. The review
    // row is created lazily when someone takes the first action.
    const documents = await this.documentsRepository.find({
      where: [
        {
          processingStatus: ProcessingStatus.AWAITING_CERTIFICATION,
          currentRepository: DocumentRepository.PENDING_REVIEW
        },
        {
          processingStatus: ProcessingStatus.READY_FOR_REVIEW,
          currentRepository: DocumentRepository.PENDING_REVIEW
        }
      ],
      order: { uploadedAt: "DESC" }
    });

    const documentIds = documents.map((doc) => doc.id);
    const reviews =
      documentIds.length === 0
        ? []
        : await this.reviewRepository.find({ where: { documentId: In(documentIds) } });
    const reviewByDocId = new Map(reviews.map((review) => [review.documentId, review]));

    const items = documents.map((doc) => ({
      documentId: doc.id,
      originalFilename: doc.originalFilename,
      make: doc.make ?? null,
      model: doc.model ?? null,
      year: doc.year ?? null,
      warrantyType: doc.warrantyType ?? null,
      country: doc.country ?? null,
      finalStatus: reviewByDocId.get(doc.id)?.finalStatus ?? ReviewFinalStatus.IN_REVIEW,
      updatedAt: reviewByDocId.get(doc.id)?.updatedAt ?? doc.updatedAt
    }));

    const visibleStatuses =
      role === UserRole.ADMIN
        ? new Set<string>([ReviewFinalStatus.IN_REVIEW, ReviewFinalStatus.REVIEWER_APPROVED])
        : new Set<string>([ReviewFinalStatus.IN_REVIEW]);

    const filtered = items.filter((item) => visibleStatuses.has(item.finalStatus));
    this.logger.log(
      `getPendingDocuments role=${role} totalReady=${documents.length} returned=${filtered.length}`
    );
    return filtered;
  }

  async updateMetadata(documentId: string, metadata: UpdateMetadataDto) {
    const document = await this.documentsService.getDocument(documentId);

    Object.assign(document, {
      make: metadata.make ?? document.make,
      model: metadata.model ?? document.model,
      year: metadata.year ?? document.year,
      warrantyType: metadata.warrantyType ?? document.warrantyType,
      country: metadata.country ?? document.country
    });

    if (metadata.metadataJson) {
      document.metadataJson = metadata.metadataJson;
    }
    if (
      metadata.vin !== undefined ||
      metadata.chassisId !== undefined ||
      metadata.purchase_date !== undefined ||
      metadata.current_mileage !== undefined
    ) {
      const existingMeta = (document.metadataJson as Record<string, unknown>) || {};
      document.metadataJson = {
        ...existingMeta,
        ...(metadata.vin !== undefined ? { vin: metadata.vin } : {}),
        ...(metadata.chassisId !== undefined ? { chassis_id: metadata.chassisId } : {}),
        ...(metadata.purchase_date !== undefined ? { purchase_date: metadata.purchase_date } : {}),
        ...(metadata.current_mileage !== undefined ? { current_mileage: metadata.current_mileage } : {})
      };
    }

    const make = metadata.make ?? document.make ?? null;
    const model = metadata.model ?? document.model ?? null;
    const year = metadata.year ?? document.year ?? null;
    const vin = metadata.vin ?? (document.metadataJson as Record<string, unknown>)?.vin ?? null;
    const chassisId =
      metadata.chassisId ??
      (document.metadataJson as Record<string, unknown>)?.chassis_id ??
      null;

    if (metadata.vin || metadata.chassisId || metadata.make || metadata.model || metadata.year) {
      await this.dataSource.query(
        `UPDATE documents
         SET master_schema_json = jsonb_set(
           jsonb_set(
             jsonb_set(
               jsonb_set(
                 jsonb_set(
                   COALESCE(master_schema_json, '{"vehicle":{}}'::jsonb),
                   '{vehicle,vin}',
                   CASE WHEN $2::text IS NOT NULL
                     THEN jsonb_build_object('value',$2,'status','extracted','confidence',1.0,'page',null)
                     ELSE COALESCE(master_schema_json->'vehicle'->'vin', 'null'::jsonb) END
                 ),
                 '{vehicle,chassis_id}',
                 CASE WHEN $3::text IS NOT NULL
                   THEN jsonb_build_object('value',$3,'status','extracted','confidence',1.0,'page',null)
                   ELSE COALESCE(master_schema_json->'vehicle'->'chassis_id', 'null'::jsonb) END
               ),
               '{vehicle,make}',
               CASE WHEN $4::text IS NOT NULL
                 THEN jsonb_build_object('value',$4,'status','extracted','confidence',1.0,'page',null)
                 ELSE COALESCE(master_schema_json->'vehicle'->'make', 'null'::jsonb) END
             ),
             '{vehicle,model}',
             CASE WHEN $5::text IS NOT NULL
               THEN jsonb_build_object('value',$5,'status','extracted','confidence',1.0,'page',null)
               ELSE COALESCE(master_schema_json->'vehicle'->'model', 'null'::jsonb) END
           ),
           '{vehicle,model_year}',
           CASE WHEN $6::int IS NOT NULL
             THEN jsonb_build_object('value',$6,'status','extracted','confidence',1.0,'page',null)
             ELSE COALESCE(master_schema_json->'vehicle'->'model_year', 'null'::jsonb) END
         ),
         required_fields_missing = NOT (
           COALESCE($4::text, make, '') <> ''
           AND (document_type = 'coverage_code_table' OR COALESCE($5::text, model, '') <> '')
         )
         WHERE id = $1`,
        [documentId, vin, chassisId, make, model, year]
      );
    }

    await this.documentsService.saveDocument(document);
    return this.documentsService.getDocument(documentId);
  }

  async reviewerApprove(documentId: string, userId: string, comment?: string) {
    this.logger.log(`reviewerApprove start documentId=${documentId} userId=${userId}`);
    const review = await this.getOrCreateReview(documentId);
    review.reviewerId = userId;
    review.reviewerApprovedAt = new Date();
    review.reviewerComment = comment;
    review.finalStatus = ReviewFinalStatus.REVIEWER_APPROVED;
    const saved = await this.reviewRepository.save(review);
    this.logger.log(`reviewerApprove postgres saved documentId=${documentId} finalStatus=${saved.finalStatus}`);

    await this.setQdrantRepository(documentId, DocumentRepository.REVIEWER_APPROVED);
    this.logger.log(`reviewerApprove done documentId=${documentId}`);
    return saved;
  }

  async adminApprove(documentId: string, userId: string, comment?: string) {
    this.logger.log(`adminApprove start documentId=${documentId} userId=${userId}`);

    const docForGate = await this.documentsRepository.findOne({ where: { id: documentId } });
    if (!docForGate) {
      throw new NotFoundException("Document not found");
    }
    if (docForGate.requiredFieldsMissing) {
      const hasMake = !!docForGate.make;
      const hasModel = !!docForGate.model;
      const isCoverageTable = docForGate.documentType === "coverage_code_table";
      const hasIdentifiers = hasMake && (isCoverageTable || hasModel);
      if (!hasIdentifiers) {
        throw new BadRequestException(
          isCoverageTable
            ? "Required fields missing: Make must be filled before certification."
            : "Required fields missing: Make and Model must be filled before certification. Use PATCH /review/:id/metadata to fill them."
        );
      }
    }

    const review = await this.getOrCreateReview(documentId);
    const document = await this.documentsService.getDocument(documentId);
    const canCertifyDirect =
      document.processingStatus === ProcessingStatus.AWAITING_CERTIFICATION;
    if (
      !canCertifyDirect &&
      review.finalStatus !== ReviewFinalStatus.REVIEWER_APPROVED
    ) {
      throw new BadRequestException("Document must be reviewer approved first");
    }
    const toKey = `certified/${document.country || "unknown"}/${document.make || "unknown"}/${document.model || "unknown"}/${document.year || "unknown"}/${documentId}/original.pdf`;
    this.logger.log(`adminApprove moving s3 ${document.s3Path} -> ${toKey}`);

    // Verify source exists before moving; handle path inconsistencies
    const sourceExists = await this.s3Service.objectExists(document.s3Path);
    const destExists = await this.s3Service.objectExists(toKey);

    if (destExists) {
      this.logger.log(`adminApprove: file already at destination ${toKey}, skipping move`);
    } else if (sourceExists) {
      await this.s3Service.moveObject(document.s3Path, toKey);
    } else {
      // Try alternate source paths (private-session vs pending-review)
      const altKey = document.s3Path.replace("pending-review/", "private-session/");
      const altExists = await this.s3Service.objectExists(altKey);
      if (altExists) {
        this.logger.warn(`adminApprove: source at alternate path ${altKey}, moving from there`);
        await this.s3Service.moveObject(altKey, toKey);
      } else {
        this.logger.error(`adminApprove: source file not found at ${document.s3Path} or ${altKey}`);
        throw new NotFoundException(`Source file not found in S3 for document ${documentId}`);
      }
    }
    Object.assign(document, {
      s3Path: toKey,
      currentRepository: DocumentRepository.CERTIFIED
    });
    await this.documentsService.saveDocument(document);
    this.logger.log(`adminApprove documents row updated to certified documentId=${documentId}`);

    const warrantyType = await this.determineWarrantyType(docForGate);
    await this.documentsRepository.update(documentId, { warrantyType });
    this.logger.log(`adminApprove warrantyType=${warrantyType} documentId=${documentId}`);

    review.adminId = userId;
    review.adminApprovedAt = new Date();
    review.adminComment = comment;
    review.finalStatus = ReviewFinalStatus.CERTIFIED;
    const saved = await this.reviewRepository.save(review);
    this.logger.log(`adminApprove reviews row updated documentId=${documentId} finalStatus=${saved.finalStatus}`);

    try {
      await this.setQdrantRepository(documentId, DocumentRepository.CERTIFIED);
    } catch (err: any) {
      this.logger.warn(
        `adminApprove Qdrant flip skipped (Act 2 will index): ${err?.message ?? err}`
      );
    }

    const aiUrl = process.env.AI_SERVICE_URL;
    if (aiUrl) {
      const processUrl = `${aiUrl.replace(/\/$/, "")}/internal/process/${documentId}`;
      this.logger.log(`adminApprove triggering Act 2 -> ${processUrl}`);
      fetch(processUrl, { method: "POST" })
        .then((res) => {
          if (!res.ok) {
            this.logger.warn(`Act 2 trigger returned ${res.status} for ${documentId}`);
          } else {
            this.logger.log(`Act 2 trigger accepted for ${documentId}`);
          }
        })
        .catch((err) =>
          this.logger.error(`Act 2 trigger failed for ${documentId}: ${err?.message ?? err}`)
        );
    }

    this.logger.log(`adminApprove done documentId=${documentId}`);
    return saved;
  }

  async reject(documentId: string, userId: string, reason: string) {
    this.logger.log(`reject start documentId=${documentId} userId=${userId}`);
    const review = await this.getOrCreateReview(documentId);
    const document = await this.documentsService.getDocument(documentId);
    const toKey = `rejected-archive/${documentId}/original.pdf`;
    this.logger.log(`reject moving s3 ${document.s3Path} -> ${toKey}`);
    await this.s3Service.moveObject(document.s3Path, toKey);

    Object.assign(document, {
      s3Path: toKey,
      currentRepository: DocumentRepository.REJECTED
    });
    await this.documentsService.saveDocument(document);

    review.rejectedBy = userId;
    review.rejectionReason = reason;
    review.finalStatus = ReviewFinalStatus.REJECTED;
    const saved = await this.reviewRepository.save(review);
    this.logger.log(`reject postgres saved documentId=${documentId}`);

    await this.setQdrantRepository(documentId, DocumentRepository.REJECTED);
    this.logger.log(`reject done documentId=${documentId}`);
    return saved;
  }

  async getReviewState(documentId: string) {
    // Returns current workflow state for detail page button visibility.
    const document = await this.documentsService.getDocument(documentId);
    const review = await this.reviewRepository.findOne({ where: { documentId } });
    const finalStatus = review?.finalStatus ?? ReviewFinalStatus.IN_REVIEW;
    const isPendingRepository = document.currentRepository === DocumentRepository.PENDING_REVIEW;

    return {
      documentId: document.id,
      currentRepository: document.currentRepository,
      processingStatus: document.processingStatus,
      finalStatus,
      canReviewerApprove: isPendingRepository && finalStatus === ReviewFinalStatus.IN_REVIEW,
      canAdminApprove:
        isPendingRepository &&
        (document.processingStatus === ProcessingStatus.AWAITING_CERTIFICATION ||
          finalStatus === ReviewFinalStatus.REVIEWER_APPROVED),
      canReject:
        isPendingRepository &&
        finalStatus !== ReviewFinalStatus.CERTIFIED &&
        finalStatus !== ReviewFinalStatus.REJECTED
    };
  }

  private async setQdrantRepository(documentId: string, repository: string): Promise<void> {
    // Calls the AI service so that every Qdrant chunk for this document
    // gets its `repository` payload flipped. Without this step, certified
    // documents would never become visible to chat search.
    const baseUrl = process.env.AI_SERVICE_URL;
    if (!baseUrl) {
      this.logger.error("AI_SERVICE_URL is not set, cannot update Qdrant repository tag");
      throw new Error("AI_SERVICE_URL is not configured");
    }
    const url = `${baseUrl}/internal/set-repository/${documentId}`;
    this.logger.log(`Qdrant flip request -> ${url} repository=${repository}`);
    let response: Response;
    try {
      response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repository })
      });
    } catch (err: any) {
      this.logger.error(
        `Qdrant flip network error documentId=${documentId} repository=${repository} error=${err?.message ?? err}`
      );
      throw new Error(`Failed to reach AI service: ${err?.message ?? err}`);
    }

    const text = await response.text();
    if (!response.ok) {
      this.logger.error(
        `Qdrant flip failed documentId=${documentId} repository=${repository} status=${response.status} body=${text}`
      );
      throw new Error(`AI service returned ${response.status}: ${text}`);
    }
    this.logger.log(
      `Qdrant flip ok documentId=${documentId} repository=${repository} response=${text}`
    );
  }

  private async getOrCreateReview(documentId: string): Promise<ReviewEntity> {
    // This function returns existing review row or creates a new one.
    const document = await this.documentsService.getDocument(documentId).catch(() => null);
    if (!document) {
      throw new NotFoundException("Document not found");
    }
    const existing = await this.reviewRepository.findOne({ where: { documentId } });
    if (existing) {
      return existing;
    }
    const created = this.reviewRepository.create({ documentId, finalStatus: ReviewFinalStatus.IN_REVIEW });
    return this.reviewRepository.save(created);
  }
  private normalizeMake(make?: string | null): string {
    return (make || "")
      .trim()
      .toLowerCase()
      .replace(/\btruck\b/g, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  private normalizeModel(model?: string | null): string {
    return (model || "").trim().toLowerCase().replace(/\s+/g, "");
  }

  /** VIN if present anywhere we know to look, else chassis ID, else null. */
  private extractIdentifier(doc: DocumentEntity): string | null {
    const meta = (doc.metadataJson as Record<string, any>) || {};
    const schema = (doc.masterSchemaJson as Record<string, any>) || {};
    const vehicle = schema.vehicle || {};
    const vin = meta.vin || vehicle.vin?.value || null;
    const chassis = meta.chassis_id || vehicle.chassis_id?.value || null;
    const id = String(vin || chassis || "").trim().toUpperCase();
    return id || null;
  }

  /**
   * Standard = first certified document for this Make+Model+Year.
   * Non-Standard = another certified document already exists for the same Make+Model+Year
   * with a different (or missing-on-either-side) VIN/Chassis — a VIN-specific extended
   * warranty layered on top of the standard one for that vehicle type.
   */
  async determineWarrantyType(doc: DocumentEntity): Promise<"standard" | "non_standard"> {
    if (!doc.make || !doc.model) return "standard";
    const candidates = await this.documentsRepository.find({
      where: { currentRepository: DocumentRepository.CERTIFIED },
    });
    const myMake = this.normalizeMake(doc.make);
    const myModel = this.normalizeModel(doc.model);
    const myId = this.extractIdentifier(doc);

    for (const other of candidates) {
      if (other.id === doc.id) continue;
      if (this.normalizeMake(other.make) !== myMake) continue;
      if (this.normalizeModel(other.model) !== myModel) continue;
      if (String(other.year || "") !== String(doc.year || "")) continue;

      const otherId = this.extractIdentifier(other);
      if (!myId || !otherId || myId !== otherId) {
        return "non_standard";
      }
    }
    return "standard";
  }
}
