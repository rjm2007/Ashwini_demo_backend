import { IsOptional, IsString } from "class-validator";

export class AdminApproveDto {
  @IsOptional()
  @IsString()
  comment?: string;
}
