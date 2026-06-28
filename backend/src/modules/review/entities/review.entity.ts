import { Column, CreateDateColumn, Entity, PrimaryGeneratedColumn, UpdateDateColumn } from "typeorm";

export enum ReviewFinalStatus {
  IN_REVIEW = "in_review",
  REVIEWER_APPROVED = "reviewer_approved",
  CERTIFIED = "certified",
  REJECTED = "rejected"
}

@Entity("reviews")
export class ReviewEntity {
  @PrimaryGeneratedColumn("uuid")
  id!: string;

  @Column({ name: "document_id", unique: true })
  documentId!: string;

  @Column({ name: "reviewer_id", nullable: true })
  reviewerId?: string;

  @Column({ name: "reviewer_approved_at", nullable: true })
  reviewerApprovedAt?: Date;

  @Column({ name: "reviewer_comment", type: "text", nullable: true })
  reviewerComment?: string;

  @Column({ name: "admin_id", nullable: true })
  adminId?: string;

  @Column({ name: "admin_approved_at", nullable: true })
  adminApprovedAt?: Date;

  @Column({ name: "admin_comment", type: "text", nullable: true })
  adminComment?: string;

  @Column({ name: "rejected_by", nullable: true })
  rejectedBy?: string;

  @Column({ name: "rejection_reason", type: "text", nullable: true })
  rejectionReason?: string;

  @Column({ name: "final_status", type: "enum", enum: ReviewFinalStatus, default: ReviewFinalStatus.IN_REVIEW })
  finalStatus!: ReviewFinalStatus;

  @CreateDateColumn({ name: "created_at" })
  createdAt!: Date;

  @UpdateDateColumn({ name: "updated_at" })
  updatedAt!: Date;
}
