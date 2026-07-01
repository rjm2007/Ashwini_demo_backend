import { TypeOrmModuleOptions } from "@nestjs/typeorm";
import { UserEntity } from "../database/entities/user.entity";
import { DocumentEntity } from "../modules/documents/entities/document.entity";
import { ReviewEntity } from "../modules/review/entities/review.entity";
import { QuerySessionEntity } from "../modules/query/entities/query-session.entity";
import { QueryMessageEntity } from "../modules/query/entities/query-message.entity";
import { DefectEntity } from "../modules/defects/entities/defect.entity";
import { DefectMessageEntity } from "../modules/defects/entities/defect-message.entity";
import { SupportTicketEntity } from "../modules/support/entities/support-ticket.entity";
import { AgentPromptEntity } from "../modules/vapi-agents/entities/agent-prompt.entity";
import { CallLogEntity } from "../modules/calls/entities/call-log.entity";

export function buildDatabaseConfig(): TypeOrmModuleOptions {
  // This function builds TypeORM configuration from env variables.
  return {
    type: "postgres",
    url: process.env.DATABASE_URL,
    entities: [
      UserEntity,
      DocumentEntity,
      ReviewEntity,
      QuerySessionEntity,
      QueryMessageEntity,
      DefectEntity,
      DefectMessageEntity,
      SupportTicketEntity,
      AgentPromptEntity,
      CallLogEntity
    ],
    synchronize: false
  };
}