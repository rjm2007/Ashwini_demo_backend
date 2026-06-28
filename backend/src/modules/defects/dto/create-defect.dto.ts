import { IsDateString, IsInt, IsOptional, IsString, IsUUID, Min, MinLength } from "class-validator";

export class CreateDefectDto {
  @IsUUID()
  documentId!: string;

  @IsString()
  @MinLength(3)
  reportedDefect!: string;

  @IsOptional()
  @IsDateString()
  purchaseDate?: string;

  @IsOptional()
  @IsInt()
  @Min(0)
  currentMileage?: number;
}
