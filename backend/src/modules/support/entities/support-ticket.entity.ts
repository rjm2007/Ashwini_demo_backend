import { Column, CreateDateColumn, Entity, PrimaryGeneratedColumn } from "typeorm";

@Entity("support_tickets")
export class SupportTicketEntity {
  @PrimaryGeneratedColumn("uuid")
  id!: string;

  @Column({ name: "document_id", nullable: true })
  documentId?: string;

  @Column({ name: "session_id", nullable: true })
  sessionId?: string;

  @Column({ name: "raised_by", nullable: true })
  raisedBy?: string;

  @Column({ nullable: true })
  question?: string;

  @Column({ name: "answer_snapshot", nullable: true })
  answerSnapshot?: string;

  @Column({ nullable: true })
  note?: string;

  @Column({ default: "open" })
  status!: string;

  @CreateDateColumn({ name: "created_at" })
  createdAt!: Date;
}
