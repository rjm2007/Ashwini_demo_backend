import { Column, CreateDateColumn, Entity, PrimaryGeneratedColumn } from "typeorm";

export enum QueryMessageRole {
  USER = "user",
  ASSISTANT = "assistant"
}

@Entity("query_messages")
export class QueryMessageEntity {
  @PrimaryGeneratedColumn("uuid")
  id!: string;

  @Column({ name: "session_id" })
  sessionId!: string;

  @Column({ type: "enum", enum: QueryMessageRole })
  role!: QueryMessageRole;

  @Column({ type: "text" })
  content!: string;

  @Column({ name: "evidence_json", type: "jsonb", nullable: true })
  evidenceJson?: Record<string, unknown> | unknown[];

  @Column({ name: "confidence_score", type: "float", nullable: true })
  confidenceScore?: number;

  @Column({ name: "metadata_filters_applied_json", type: "jsonb", nullable: true })
  metadataFiltersAppliedJson?: Record<string, unknown>;

  @CreateDateColumn({ name: "created_at" })
  createdAt!: Date;
}
