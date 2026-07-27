import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { VapiAgentsController } from "./vapi-agents.controller";
import { VapiAgentsService } from "./vapi-agents.service";
import { AgentPromptEntity } from "./entities/agent-prompt.entity";
import { AppSettingsModule } from "../app-settings/app-settings.module";

@Module({
  imports: [TypeOrmModule.forFeature([AgentPromptEntity]), AppSettingsModule],
  controllers: [VapiAgentsController],
  providers: [VapiAgentsService]
})
export class VapiAgentsModule {}

