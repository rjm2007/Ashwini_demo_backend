import { IsString, MinLength } from "class-validator";

export class RejectDto {
  @IsString()
  @MinLength(3)
  reason!: string;
}
