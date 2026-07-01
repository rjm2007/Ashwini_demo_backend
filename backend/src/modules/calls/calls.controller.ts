import { Body, Controller, Get, Param, Post, Req, UseGuards } from "@nestjs/common";
import { Request } from "express";
import { Roles } from "../../common/decorators/roles.decorator";
import { RolesGuard } from "../../common/guards/roles.guard";
import { UserRole } from "../../common/enums/user-role.enum";
import { CallsService } from "./calls.service";
import { StartCallDto } from "./dto/start-call.dto";

@Controller("calls")
@UseGuards(RolesGuard)
export class CallsController {
  constructor(private readonly callsService: CallsService) {}

  @Post()
  @Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
  async startCall(@Body() dto: StartCallDto, @Req() req: Request & { user?: any }) {
    return this.callsService.startCall(dto.vapiCallId, dto.agentKey, dto.agentName, req.user?.userId, req.user?.email);
  }

  @Get()
  @Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
  async findAll(@Req() req: Request & { user?: any }) {
    return this.callsService.findAll(req.user?.userId, req.user?.role);
  }

  @Get(":id")
  @Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
  async findOne(@Param("id") id: string, @Req() req: Request & { user?: any }) {
    return this.callsService.findOne(id, req.user?.userId, req.user?.role);
  }
}
