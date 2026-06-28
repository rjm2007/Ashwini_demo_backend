import { Column, CreateDateColumn, Entity, PrimaryGeneratedColumn } from "typeorm";
import { UserRole } from "../../common/enums/user-role.enum";

@Entity("users")
export class UserEntity {
  @PrimaryGeneratedColumn("uuid")
  id!: string;

  @Column({ unique: true })
  email!: string;

  @Column({ name: "password_hash" })
  passwordHash!: string;

  @Column()
  name!: string;

  @Column({ type: "enum", enum: UserRole })
  role!: UserRole;

  @CreateDateColumn({ name: "created_at" })
  createdAt!: Date;
}
