import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { DocumentEntity } from "./entities/document.entity";
import { DocumentsController } from "./documents.controller";
import { DocumentsService } from "./documents.service";
import { S3Service } from "./s3.service";

@Module({
  imports: [TypeOrmModule.forFeature([DocumentEntity])],
  controllers: [DocumentsController],
  providers: [DocumentsService, S3Service],
  exports: [DocumentsService, S3Service]
})
export class DocumentsModule {}
