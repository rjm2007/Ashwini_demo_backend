import {
  Entity,
  PrimaryGeneratedColumn,
  Column,
  CreateDateColumn,
  UpdateDateColumn
} from "typeorm";

@Entity("defects")
export class DefectEntity {
  @PrimaryGeneratedColumn("uuid")
  id!: string;

  @Column({ name: "document_id", type: "uuid" })
  documentId!: string;

  @Column({ name: "created_by", type: "uuid" })
  createdBy!: string;

  @Column({ name: "reported_defect", type: "text" })
  reportedDefect!: string;

  @Column({ name: "purchase_date", type: "date", nullable: true })
  purchaseDate?: Date;

  @Column({ name: "current_mileage", type: "int", nullable: true })
  currentMileage?: number;

  @Column({ nullable: true })
  make?: string;

  @Column({ name: "warranty_type", type: "varchar", length: 20, nullable: true })
  warrantyType?: string;

  @Column({ nullable: true })
  model?: string;

  @Column({ nullable: true })
  year?: number;

  @Column({ name: "primary_decision", nullable: true })
  primaryDecision?: string;

  @Column({ name: "primary_component", nullable: true })
  primaryComponent?: string;

  @Column({ name: "primary_coverage_id", type: "varchar", nullable: true })
  primaryCoverageId?: string;

  @Column({ name: "overall_confidence_score", type: "float", nullable: true })
  overallConfidenceScore?: number;

  @Column({ name: "context_json", type: "jsonb", nullable: true })
  contextJson?: Record<string, unknown>;

  @CreateDateColumn({ name: "created_at" })
  createdAt!: Date;

  @UpdateDateColumn({ name: "updated_at" })
  updatedAt!: Date;
}
