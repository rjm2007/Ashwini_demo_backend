import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { buildDatabaseConfig } from "../config/database.config";

@Module({
  imports: [TypeOrmModule.forRootAsync({ useFactory: () => buildDatabaseConfig() })]
})
export class DatabaseModule {}
