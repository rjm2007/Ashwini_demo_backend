import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { DocumentsModule } from "../documents/documents.module";
import { DocumentEntity } from "../documents/entities/document.entity";
import { ReviewEntity } from "./entities/review.entity";
import { ReviewController } from "./review.controller";
import { ReviewService } from "./review.service";

@Module({
  imports: [TypeOrmModule.forFeature([ReviewEntity, DocumentEntity]), DocumentsModule],
  controllers: [ReviewController],
  providers: [ReviewService]
})
export class ReviewModule {}
