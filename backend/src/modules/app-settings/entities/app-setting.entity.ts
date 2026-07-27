import { Column, Entity, PrimaryColumn, UpdateDateColumn } from "typeorm";

@Entity("app_settings")
export class AppSettingEntity {
  @PrimaryColumn({ name: "setting_key", type: "varchar", length: 64 })
  settingKey!: string;

  /** AES-256-GCM envelope — never plaintext. See crypto.util.ts. */
  @Column({ name: "encrypted_value", type: "text" })
  encryptedValue!: string;

  @Column({ name: "is_secret", type: "boolean", default: true })
  isSecret!: boolean;

  @Column({ name: "updated_by", type: "uuid", nullable: true })
  updatedBy!: string | null;

  @UpdateDateColumn({ name: "updated_at" })
  updatedAt!: Date;
}
