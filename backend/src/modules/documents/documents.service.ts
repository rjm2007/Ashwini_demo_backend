import { BadRequestException, Injectable, Logger, NotFoundException } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { SendMessageCommand } from "@aws-sdk/client-sqs";
import { DataSource, ILike, Repository } from "typeorm";
import { v4 as uuidv4 } from "uuid";
import { sqsClient } from "../../config/aws.config";
import { DocumentEntity } from "./entities/document.entity";
import { DocumentRepository, ProcessingStatus } from "./entities/document-status.enum";
import { S3Service } from "./s3.service";
import { ListDocumentsDto } from "./dto/list-documents.dto";

@Injectable()
export class DocumentsService {
  private readonly logger = new Logger(DocumentsService.name);

  constructor(
    @InjectRepository(DocumentEntity)
    private readonly documentsRepository: Repository<DocumentEntity>,
    private readonly s3Service: S3Service,
    private readonly dataSource: DataSource
  ) {}

  async uploadDocument(file: Express.Multer.File, userId: string, documentType?: string) {
    const normalizedName = file.originalname.trim();
    const duplicate = await this.documentsRepository.findOne({
      where: {
        originalFilename: ILike(normalizedName)
      },
      order: {
        uploadedAt: "DESC"
      }
    });
    if (duplicate) {
      this.logger.warn(
        `uploadDocument duplicate blocked filename="${normalizedName}" existingId=${duplicate.id} repository=${duplicate.currentRepository}`
      );
      throw new BadRequestException(
        `A document with filename "${normalizedName}" already exists (id: ${duplicate.id}, repository: ${duplicate.currentRepository}).`
      );
    }

    const documentId = uuidv4();
    const s3Key = `private-session/${documentId}/original.pdf`;
    this.logger.log(
      `uploadDocument start documentId=${documentId} userId=${userId} filename="${file.originalname}" sizeBytes=${file.size} mime=${file.mimetype}`
    );

    this.logger.log(`uploadDocument s3 put -> ${s3Key}`);
    await this.s3Service.uploadFile(s3Key, file.buffer, file.mimetype);
    this.logger.log(`uploadDocument s3 put done documentId=${documentId}`);

    const document = this.documentsRepository.create({
      id: documentId,
      originalFilename: file.originalname,
      s3Path: s3Key,
      currentRepository: DocumentRepository.PENDING_REVIEW,
      processingStatus: ProcessingStatus.UPLOADED,
      uploadedBy: userId,
    });
    await this.documentsRepository.save(document);
    this.logger.log(`uploadDocument postgres row created documentId=${documentId}`);

    const aiUrl = process.env.AI_SERVICE_URL;
    if (aiUrl) {
      const parseUrl = `${aiUrl.replace(/\/$/, "")}/internal/parse/${documentId}`;
      this.logger.log(`uploadDocument triggering Act 1 parse -> ${parseUrl}`);
      fetch(parseUrl, { method: "POST" })
        .then((res) => {
          if (!res.ok) {
            this.logger.warn(`Act 1 trigger returned ${res.status} for ${documentId}`);
          } else {
            this.logger.log(`Act 1 trigger accepted for ${documentId}`);
          }
        })
        .catch((err) =>
          this.logger.error(`Act 1 trigger failed for ${documentId}: ${err?.message ?? err}`)
        );
    } else {
      const queueUrl = process.env.SQS_QUEUE_URL;
      if (!queueUrl) {
        this.logger.warn(
          `AI_SERVICE_URL and SQS_QUEUE_URL not set; processing must be triggered manually for ${documentId}`
        );
      } else {
        try {
          await sqsClient.send(
            new SendMessageCommand({
              QueueUrl: queueUrl,
              MessageBody: JSON.stringify({
                documentId,
                s3Path: s3Key,
                uploadedBy: userId,
                stage: "act1"
              })
            })
          );
          this.logger.log(`uploadDocument sqs enqueued Act 1 documentId=${documentId}`);
        } catch (err: any) {
          this.logger.error(
            `uploadDocument sqs enqueue failed documentId=${documentId} error=${err?.message ?? err}`
          );
        }
      }
    }

    this.logger.log(`uploadDocument done documentId=${documentId}`);
    return {
      documentId,
      filename: file.originalname,
      status: ProcessingStatus.UPLOADED,
      message: "Document uploaded and queued for processing."
    };
  }

  async listDocuments(filters: ListDocumentsDto) {
    // This function lists documents with optional status/repository filters.
    const page = filters.page || 1;
    const limit = filters.limit || 20;
    const query = this.documentsRepository.createQueryBuilder("documents");
    if (filters.repository) {
      query.andWhere("documents.current_repository = :repo", { repo: filters.repository });
    }
    if (filters.status) {
      query.andWhere("documents.processing_status = :status", { status: filters.status });
    }
    query.orderBy("documents.uploaded_at", "DESC").skip((page - 1) * limit).take(limit);
    const [data, total] = await query.getManyAndCount();
    const enriched = data.map((doc) => {
      const schema = (doc.masterSchemaJson || {}) as Record<string, unknown>;
      const rows = Array.isArray(schema.coverage_components) ? schema.coverage_components : [];
      return { ...doc, coverageCount: rows.length };
    });
    return { data: enriched, total, page, limit };
  }

  async getDocument(id: string) {
    // This function returns one document or throws 404.
    const document = await this.documentsRepository.findOne({ where: { id } });
    if (!document) {
      throw new NotFoundException("Document not found");
    }
    const meta = (document.metadataJson as Record<string, any>) || {};
    (document as any).assetPurchaseDate = meta.purchase_date ?? null;
    (document as any).assetCurrentMileage = meta.current_mileage ?? null;
    return document;
  }

  async getPdfSignedUrl(id: string) {
    // This function returns a secure temporary URL for document PDF.
    const document = await this.getDocument(id);
    const url = await this.s3Service.getSignedUrl(document.s3Path, 300);
    return { url, expiresInSeconds: 300 };
  }

  async saveDocument(document: DocumentEntity) {
    // This function persists document changes made by review and pipeline modules.
    return this.documentsRepository.save(document);
  }

  async getPipelineEvents(documentId: string): Promise<any[]> {
    return this.dataSource.query(
      `SELECT id, act, stage, step_key, step_label, status, detail, duration_ms, sequence, created_at
       FROM pipeline_events WHERE document_id = $1 ORDER BY sequence ASC`,
      [documentId]
    );
  }

  async getDocumentSummary(documentId: string): Promise<any> {
    const doc = await this.documentsRepository.findOne({ where: { id: documentId } });
    if (!doc) {
      throw new NotFoundException("Document not found");
    }

    const schema = (doc.masterSchemaJson ?? {}) as Record<string, any>;
    const rows = Array.isArray(schema.coverage_components) ? schema.coverage_components : [];
    const withTime = rows.filter((r) => r?.coverage_period?.duration_months != null).length;
    const withMileage = rows.filter(
      (r) =>
        r?.coverage_period?.mileage_limit != null ||
        r?.coverage_period?.mileage_unit === "unlimited"
    ).length;

    return {
      documentId: doc.id,
      filename: doc.originalFilename,
      documentType: doc.documentType ?? schema?.document?.document_type ?? null,
      completeness: doc.completeness ?? 0,
      requiredFieldsMissing: doc.requiredFieldsMissing ?? true,
      warrantyType: doc.warrantyType,
      ...schema,
      stats: {
        coverage_count: rows.length,
        with_time_limit: withTime,
        with_mileage_limit: withMileage,
        with_limit_of_liability: rows.filter((r) => r?.limit_of_liability).length,
        with_deductible: rows.filter((r) => r?.deductible).length,
        extraction_confidence: schema?.document?.extraction_confidence ?? null
      }
    };
  }
}
