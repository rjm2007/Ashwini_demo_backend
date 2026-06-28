import { Module } from "@nestjs/common";
import { TypeOrmModule } from "@nestjs/typeorm";
import { DefectsController } from "./defects.controller";
import { DefectsService } from "./defects.service";
import { DefectEntity } from "./entities/defect.entity";
import { DefectMessageEntity } from "./entities/defect-message.entity";
import { DocumentEntity } from "../documents/entities/document.entity";

@Module({
  imports: [TypeOrmModule.forFeature([DefectEntity, DefectMessageEntity, DocumentEntity])],
  controllers: [DefectsController],
  providers: [DefectsService]
})
export class DefectsModule {}
