import { IsOptional, IsString } from "class-validator";

export class ReviewerApproveDto {
  @IsOptional()
  @IsString()
  comment?: string;
}
