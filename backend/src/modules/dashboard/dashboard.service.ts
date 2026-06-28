import { Injectable } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import { DocumentEntity } from "../documents/entities/document.entity";
import { QueryMessageEntity, QueryMessageRole } from "../query/entities/query-message.entity";

@Injectable()
export class DashboardService {
  constructor(
    @InjectRepository(DocumentEntity)
    private readonly documentsRepository: Repository<DocumentEntity>,
    @InjectRepository(QueryMessageEntity)
    private readonly messagesRepository: Repository<QueryMessageEntity>
  ) {}

  async getStats() {
    // This function composes dashboard counters from documents and query messages.
    const totalDocuments = await this.documentsRepository.count();
    const docs = await this.documentsRepository.find();
    const assistantMessages = await this.messagesRepository.find({
      where: { role: QueryMessageRole.ASSISTANT }
    });
    const averageConfidence =
      assistantMessages.length === 0
        ? 0
        : assistantMessages.reduce((sum, item) => sum + (item.confidenceScore || 0), 0) /
          assistantMessages.length;

    return {
      totalDocuments,
      repositoryBreakdown: docs.reduce<Record<string, number>>((acc, item) => {
        acc[item.currentRepository] = (acc[item.currentRepository] || 0) + 1;
        return acc;
      }, {}),
      processingStatusBreakdown: docs.reduce<Record<string, number>>((acc, item) => {
        acc[item.processingStatus] = (acc[item.processingStatus] || 0) + 1;
        return acc;
      }, {}),
      averageConfidence
    };
  }
}
