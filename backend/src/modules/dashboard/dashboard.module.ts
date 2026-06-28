import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { DocumentEntity } from "../documents/entities/document.entity";
import { QueryMessageEntity } from "../query/entities/query-message.entity";
import { DashboardController } from "./dashboard.controller";
import { DashboardService } from "./dashboard.service";

@Module({
  imports: [TypeOrmModule.forFeature([DocumentEntity, QueryMessageEntity])],
  controllers: [DashboardController],
  providers: [DashboardService]
})
export class DashboardModule {}
