import { Module } from "@nestjs/common";
import { VapiAgentsController } from "./vapi-agents.controller";
import { VapiAgentsService } from "./vapi-agents.service";

@Module({
  controllers: [VapiAgentsController],
  providers: [VapiAgentsService]
})
export class VapiAgentsModule {}
