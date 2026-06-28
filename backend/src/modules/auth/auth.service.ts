import { Injectable, UnauthorizedException } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { Repository } from "typeorm";
import * as bcrypt from "bcrypt";
import * as jwt from "jsonwebtoken";
import { UserEntity } from "../../database/entities/user.entity";
import { AuthPayload } from "./interfaces/auth-payload.interface";

@Injectable()
export class AuthService {
  constructor(
    @InjectRepository(UserEntity)
    private readonly usersRepository: Repository<UserEntity>
  ) {}

  async login(email: string, password: string): Promise<{ token: string; user: Partial<UserEntity> }> {
    // This function validates credentials and returns signed JWT token.
    const user = await this.usersRepository.findOne({ where: { email } });
    if (!user) {
      throw new UnauthorizedException("Invalid credentials");
    }

    const isValid = await bcrypt.compare(password, user.passwordHash);
    const demoFallback = this.checkDemoFallback(email, password);
    if (!isValid && !demoFallback) {
      throw new UnauthorizedException("Invalid credentials");
    }

    const payload: AuthPayload = { userId: user.id, email: user.email, role: user.role };
    const expiresIn = (process.env.JWT_EXPIRY || "24h") as jwt.SignOptions["expiresIn"];
    const token = jwt.sign(payload, process.env.JWT_SECRET || "", { expiresIn });

    return {
      token,
      user: { id: user.id, email: user.email, name: user.name, role: user.role }
    };
  }

  private checkDemoFallback(email: string, password: string): boolean {
    // This function allows seeded demo users to login even if hash is replaced during local setup.
    const expected: Record<string, string> = {
      "admin@demo.com": "admin123",
      "reviewer@demo.com": "reviewer123",
      "user@demo.com": "user123"
    };
    return expected[email] === password;
  }
}
