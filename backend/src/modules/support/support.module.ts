import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { SupportTicketEntity } from "./entities/support-ticket.entity";
import { SupportController } from "./support.controller";
import { SupportService } from "./support.service";

@Module({
  imports: [TypeOrmModule.forFeature([SupportTicketEntity])],
  controllers: [SupportController],
  providers: [SupportService]
})
export class SupportModule {}
