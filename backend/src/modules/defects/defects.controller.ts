import { Body, Controller, Get, Param, Post, Req, UseGuards } from "@nestjs/common";
import { Request } from "express";
import { Roles } from "../../common/decorators/roles.decorator";
import { RolesGuard } from "../../common/guards/roles.guard";
import { UserRole } from "../../common/enums/user-role.enum";
import { DefectsService } from "./defects.service";
import { CreateDefectDto } from "./dto/create-defect.dto";
import { SendDefectMessageDto } from "./dto/send-defect-message.dto";

@Controller("defects")
@UseGuards(RolesGuard)
export class DefectsController {
  constructor(private readonly defectsService: DefectsService) {}

  // Must be registered before ":id" so "eligible-documents" isn't swallowed as an :id param.
  @Get("eligible-documents")
  @Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
  async listEligibleDocuments() {
    return this.defectsService.listEligibleDocuments();
  }

  @Get()
  @Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
  async findAll(@Req() req: Request & { user?: any }) {
    return this.defectsService.findAll(req.user?.userId);
  }

  @Get(":id")
  @Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
  async findOne(@Param("id") id: string, @Req() req: Request & { user?: any }) {
    return this.defectsService.findOne(id, req.user?.userId);
  }

  @Post()
  @Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
  async create(@Body() createDto: CreateDefectDto, @Req() req: Request & { user?: any }) {
    return this.defectsService.create(createDto, req.user?.userId);
  }

  @Post(":id/messages")
  @Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
  async addMessage(
    @Param("id") id: string,
    @Body() messageDto: SendDefectMessageDto,
    @Req() req: Request & { user?: any }
  ) {
    return this.defectsService.addMessage(id, messageDto.content, req.user?.userId);
  }
}
