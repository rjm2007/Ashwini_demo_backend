import { Controller, Get, Param, UseGuards } from "@nestjs/common";
import { RolesGuard } from "../../common/guards/roles.guard";
import { Roles } from "../../common/decorators/roles.decorator";
import { UserRole } from "../../common/enums/user-role.enum";
import { CostService } from "./cost.service";

// Spend data. Every signed-in role can see it because the document detail
// Cost tab and the Dashboard are available to all roles; narrow this if cost
// visibility ever needs to become admin-only.
@Controller("cost")
@UseGuards(RolesGuard)
@Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
export class CostController {
  constructor(private readonly costService: CostService) {}

  @Get("document/:id")
  async documentCost(@Param("id") id: string) {
    return this.costService.getDocumentCost(id);
  }

  @Get("session/:id")
  async sessionCost(@Param("id") id: string) {
    return this.costService.getSessionCost(id);
  }

  @Get("daily")
  async dailyCost() {
    return this.costService.getDailyCost();
  }
}
