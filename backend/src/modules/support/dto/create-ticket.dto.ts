import { IsOptional, IsString, IsUUID } from "class-validator";

export class CreateTicketDto {
  @IsOptional()
  @IsUUID()
  documentId?: string;

  @IsOptional()
  @IsUUID()
  sessionId?: string;

  @IsOptional()
  @IsString()
  question?: string;

  @IsOptional()
  @IsString()
  answerSnapshot?: string;

  @IsOptional()
  @IsString()
  note?: string;
}
