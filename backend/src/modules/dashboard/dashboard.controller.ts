import { Controller, Get, UseGuards } from "@nestjs/common";
import { RolesGuard } from "../../common/guards/roles.guard";
import { Roles } from "../../common/decorators/roles.decorator";
import { UserRole } from "../../common/enums/user-role.enum";
import { DashboardService } from "./dashboard.service";

@Controller("dashboard")
@UseGuards(RolesGuard)
@Roles(UserRole.ADMIN, UserRole.REVIEWER, UserRole.USER)
export class DashboardController {
  constructor(private readonly dashboardService: DashboardService) {}

  @Get("stats")
  async getStats() {
    // This function returns aggregated dashboard data.
    return this.dashboardService.getStats();
  }
}
