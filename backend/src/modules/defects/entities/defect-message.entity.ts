import {
  Entity,
  PrimaryGeneratedColumn,
  Column,
  CreateDateColumn,
  ManyToOne,
  JoinColumn
} from "typeorm";
import { DefectEntity } from "./defect.entity";

export enum DefectMessageRole {
  USER = "user",
  ASSISTANT = "assistant"
}

@Entity("defect_messages")
export class DefectMessageEntity {
  @PrimaryGeneratedColumn("uuid")
  id!: string;

  @Column({ name: "defect_id", type: "uuid" })
  defectId!: string;

  @ManyToOne(() => DefectEntity)
  @JoinColumn({ name: "defect_id" })
  defect!: DefectEntity;

  @Column({ type: "enum", enum: DefectMessageRole })
  role!: DefectMessageRole;

  @Column({ type: "text" })
  content!: string;

  @Column({ name: "evidence_json", type: "jsonb", nullable: true })
  evidenceJson?: Record<string, unknown>;

  @Column({ name: "confidence_score", type: "float", nullable: true })
  confidenceScore?: number;

  @CreateDateColumn({ name: "created_at" })
  createdAt!: Date;
}
