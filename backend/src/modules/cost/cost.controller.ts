import { Controller, Get, Param, UseGuards } from "@nestjs/common";
import { RolesGuard } from "../../common/guards/roles.guard";
import { CostService } from "./cost.service";

@Controller("cost")
@UseGuards(RolesGuard)
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
