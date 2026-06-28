import { IsObject, IsOptional, IsString, MinLength } from "class-validator";

export class SendMessageDto {
  @IsString()
  @MinLength(2)
  content!: string;

  @IsOptional()
  @IsString()
  documentId?: string;

  @IsOptional()
  @IsObject()
  context?: Record<string, unknown>;
}
