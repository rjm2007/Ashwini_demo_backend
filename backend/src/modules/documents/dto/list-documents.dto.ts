import { IsEnum, IsInt, IsOptional, Min } from "class-validator";
import { Transform } from "class-transformer";
import { DocumentRepository, ProcessingStatus } from "../entities/document-status.enum";

export class ListDocumentsDto {
  @IsOptional()
  @IsEnum(DocumentRepository)
  repository?: DocumentRepository;

  @IsOptional()
  @IsEnum(ProcessingStatus)
  status?: ProcessingStatus;

  @IsOptional()
  @Transform(({ value }) => Number(value))
  @IsInt()
  @Min(1)
  page?: number = 1;

  @IsOptional()
  @Transform(({ value }) => Number(value))
  @IsInt()
  @Min(1)
  limit?: number = 20;
}
