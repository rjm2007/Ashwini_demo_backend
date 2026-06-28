import { Controller, Get, Post, Body, Req, UnauthorizedException } from "@nestjs/common";
import { Request } from "express";
import { AuthService } from "./auth.service";
import { LoginDto } from "./dto/login.dto";

@Controller("auth")
export class AuthController {
  constructor(private readonly authService: AuthService) {}

  @Post("login")
  async login(@Body() dto: LoginDto) {
    // This function handles login and returns token plus user profile.
    return this.authService.login(dto.email, dto.password);
  }

  @Get("me")
  getMe(@Req() req: Request & { user?: Record<string, unknown> }) {
    // This function returns user data that middleware put on request.
    if (!req.user) {
      throw new UnauthorizedException("Not authenticated");
    }
    return req.user;
  }
}
