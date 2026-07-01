import { Column, Entity, PrimaryColumn, UpdateDateColumn } from "typeorm";

@Entity("agent_prompts")
export class AgentPromptEntity {
  @PrimaryColumn({ name: "agent_key", type: "varchar", length: 32 })
  agentKey!: string;

  @Column({ type: "text" })
  prompt!: string;

  @UpdateDateColumn({ name: "updated_at" })
  updatedAt!: Date;
}
