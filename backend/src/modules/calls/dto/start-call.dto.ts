import { IsNotEmpty, IsOptional, IsString } from "class-validator";

export class StartCallDto {
  @IsNotEmpty()
  @IsString()
  vapiCallId!: string;

  @IsNotEmpty()
  @IsString()
  agentKey!: string;

  @IsOptional()
  @IsString()
  agentName?: string;
}
