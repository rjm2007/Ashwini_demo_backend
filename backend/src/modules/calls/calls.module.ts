import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { CallsController } from "./calls.controller";
import { CallsWebhookController } from "./calls-webhook.controller";
import { CallsService } from "./calls.service";
import { CallLogEntity } from "./entities/call-log.entity";

@Module({
  imports: [TypeOrmModule.forFeature([CallLogEntity])],
  controllers: [CallsController, CallsWebhookController],
  providers: [CallsService]
})
export class CallsModule {}
