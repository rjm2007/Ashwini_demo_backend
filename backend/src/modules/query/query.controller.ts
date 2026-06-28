import { Body, Controller, Delete, Get, Param, Post, Req } from "@nestjs/common";
import { Request } from "express";
import { QueryService } from "./query.service";
import { CreateSessionDto } from "./dto/create-session.dto";
import { SendMessageDto } from "./dto/send-message.dto";

@Controller("query")
export class QueryController {
  constructor(private readonly queryService: QueryService) {}

  @Post("sessions")
  async createSession(@Body() dto: CreateSessionDto, @Req() req: Request & { user?: any }) {
    // This function creates a new chat session for current user.
    return this.queryService.createSession(req.user?.userId, dto.title);
  }

  @Get("sessions")
  async listSessions(@Req() req: Request & { user?: any }) {
    // This function lists current user's sessions.
    return this.queryService.listSessions(req.user?.userId);
  }

  @Get("sessions/:id")
  async getSession(@Param("id") id: string, @Req() req: Request & { user?: any }) {
    // This function gets a session and message history.
    return this.queryService.getSession(id, req.user?.userId);
  }

  @Post("sessions/:id/messages")
  async sendMessage(
    @Param("id") id: string,
    @Body() dto: SendMessageDto,
    @Req() req: Request & { user?: any }
  ) {
    // This function sends user query and returns assistant response.
    return this.queryService.sendMessage(id, req.user?.userId, dto.content, dto.documentId, dto.context);
  }

  @Delete("sessions/:id")
  async deleteSession(@Param("id") id: string, @Req() req: Request & { user?: any }) {
    // This function removes a chat session for current user.
    return this.queryService.deleteSession(id, req.user?.userId);
  }
}
