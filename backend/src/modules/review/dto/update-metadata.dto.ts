import { IsInt, IsObject, IsOptional, IsString } from "class-validator";

export class UpdateMetadataDto {
  @IsOptional()
  @IsString()
  make?: string;

  @IsOptional()
  @IsString()
  model?: string;

  @IsOptional()
  @IsInt()
  year?: number;

  @IsOptional()
  @IsString()
  warrantyType?: string;

  @IsOptional()
  @IsString()
  country?: string;

  @IsOptional()
  @IsObject()
  metadataJson?: Record<string, unknown>;

  @IsOptional()
  @IsString()
  vin?: string;

  @IsOptional()
  @IsString()
  chassisId?: string;

  @IsOptional()
  @IsString()
  purchase_date?: string;

  @IsOptional()
  @IsInt()
  current_mileage?: number;
}
