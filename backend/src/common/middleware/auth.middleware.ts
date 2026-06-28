import { Injectable, NestMiddleware } from "@nestjs/common";
import { NextFunction, Request, Response } from "express";
import * as jwt from "jsonwebtoken";

@Injectable()
export class AuthMiddleware implements NestMiddleware {
  use(req: Request, _res: Response, next: NextFunction): void {
    // This function parses JWT from authorization header and attaches user.
    const header = req.headers.authorization;
    if (!header?.startsWith("Bearer ")) {
      next();
      return;
    }
    const token = header.replace("Bearer ", "").trim();
    try {
      const decoded = jwt.verify(token, process.env.JWT_SECRET || "") as Record<string, unknown>;
      (req as Request & { user?: Record<string, unknown> }).user = decoded;
    } catch (_error) {
      // Ignore invalid token and continue; endpoints can reject unauthenticated users.
    }
    next();
  }
}
