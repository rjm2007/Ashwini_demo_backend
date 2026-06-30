import { Body, Controller, Get, Param, Patch, UseGuards } from "@nestjs/common";
import { Roles } from "../../common/decorators/roles.decorator";
import { RolesGuard } from "../../common/guards/roles.guard";
import { UserRole } from "../../common/enums/user-role.enum";
import { VapiAgentsService } from "./vapi-agents.service";

@Controller("vapi-agents")
@UseGuards(RolesGuard)
export class VapiAgentsController {
  constructor(private readonly vapiAgentsService: VapiAgentsService) {}

  @Get()
  @Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
  listAgents() {
    return this.vapiAgentsService.listAgents();
  }

  @Get(":key/prompt")
  @Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
  getPrompt(@Param("key") key: string) {
    return this.vapiAgentsService.getSystemPrompt(key);
  }

  @Patch(":key/prompt")
  @Roles(UserRole.ADMIN)
  updatePrompt(@Param("key") key: string, @Body() body: { prompt: string }) {
    return this.vapiAgentsService.updateSystemPrompt(key, body?.prompt);
  }
}
