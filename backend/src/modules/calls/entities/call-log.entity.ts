import {
  Entity,
  PrimaryGeneratedColumn,
  Column,
  CreateDateColumn,
  UpdateDateColumn
} from "typeorm";

export enum CallLogStatus {
  IN_PROGRESS = "in_progress",
  COMPLETED = "completed",
  FAILED = "failed"
}

@Entity("call_logs")
export class CallLogEntity {
  @PrimaryGeneratedColumn("uuid")
  id!: string;

  @Column({ name: "vapi_call_id", type: "varchar", length: 128, nullable: true, unique: true })
  vapiCallId?: string;

  @Column({ name: "agent_key", type: "varchar", length: 32 })
  agentKey!: string;

  @Column({ name: "agent_name", type: "varchar", length: 128, nullable: true })
  agentName?: string;

  @Column({ name: "created_by", type: "uuid", nullable: true })
  createdBy?: string;

  @Column({ name: "created_by_email", type: "varchar", length: 255, nullable: true })
  createdByEmail?: string;

  @Column({ type: "enum", enum: CallLogStatus, default: CallLogStatus.IN_PROGRESS })
  status!: CallLogStatus;

  @Column({ name: "event_description", type: "varchar", length: 255, nullable: true })
  eventDescription?: string;

  @Column({ type: "text", nullable: true })
  summary?: string;

  @Column({ type: "text", nullable: true })
  recommendation?: string;

  @Column({ name: "documents_collected", type: "jsonb", default: () => "'[]'::jsonb" })
  documentsCollected!: string[];

  @Column({ name: "documents_pending", type: "jsonb", default: () => "'[]'::jsonb" })
  documentsPending!: string[];

  @Column({ type: "text", nullable: true })
  transcript?: string;

  @Column({ name: "transcript_messages_json", type: "jsonb", default: () => "'[]'::jsonb" })
  transcriptMessagesJson!: Record<string, unknown>[];

  @Column({ name: "ended_reason", type: "varchar", length: 128, nullable: true })
  endedReason?: string;

  @Column({ name: "started_at", type: "timestamp" })
  startedAt!: Date;

  @Column({ name: "ended_at", type: "timestamp", nullable: true })
  endedAt?: Date;

  @CreateDateColumn({ name: "created_at" })
  createdAt!: Date;

  @UpdateDateColumn({ name: "updated_at" })
  updatedAt!: Date;
}
