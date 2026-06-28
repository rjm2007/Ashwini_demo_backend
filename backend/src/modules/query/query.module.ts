import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { QueryController } from "./query.controller";
import { QueryService } from "./query.service";
import { QuerySessionEntity } from "./entities/query-session.entity";
import { QueryMessageEntity } from "./entities/query-message.entity";

@Module({
  imports: [TypeOrmModule.forFeature([QuerySessionEntity, QueryMessageEntity])],
  controllers: [QueryController],
  providers: [QueryService]
})
export class QueryModule {}
