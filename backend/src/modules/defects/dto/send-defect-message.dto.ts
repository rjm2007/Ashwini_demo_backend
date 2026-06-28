import { IsString, MinLength } from "class-validator";

export class SendDefectMessageDto {
  @IsString()
  @MinLength(1)
  content!: string;
}
