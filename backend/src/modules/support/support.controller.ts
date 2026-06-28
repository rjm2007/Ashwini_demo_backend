import { Body, Controller, Post, Req, UseGuards } from "@nestjs/common";
import { Request } from "express";
import { Roles } from "../../common/decorators/roles.decorator";
import { UserRole } from "../../common/enums/user-role.enum";
import { RolesGuard } from "../../common/guards/roles.guard";
import { CreateTicketDto } from "./dto/create-ticket.dto";
import { SupportService } from "./support.service";

@Controller("support")
@UseGuards(RolesGuard)
export class SupportController {
  constructor(private readonly supportService: SupportService) {}

  @Post("tickets")
  @Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
  async createTicket(@Body() dto: CreateTicketDto, @Req() req: Request & { user?: any }) {
    return this.supportService.createTicket(dto, req.user?.userId);
  }
}
