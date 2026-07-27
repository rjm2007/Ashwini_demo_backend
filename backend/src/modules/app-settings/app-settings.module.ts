import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { AppSettingEntity } from "./entities/app-setting.entity";
import { AppSettingsService } from "./app-settings.service";
import { AppSettingsController } from "./app-settings.controller";

@Module({
  imports: [TypeOrmModule.forFeature([AppSettingEntity])],
  controllers: [AppSettingsController],
  providers: [AppSettingsService],
  // Exported so other modules (currently vapi-agents) can resolve credentials
  // database-first instead of reading process.env directly.
  exports: [AppSettingsService]
})
export class AppSettingsModule {}
