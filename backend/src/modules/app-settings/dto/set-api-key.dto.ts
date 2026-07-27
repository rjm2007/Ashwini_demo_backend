import { IsOptional, IsString, MaxLength, MinLength } from "class-validator";

export class SetApiKeyDto {
  // Upper bound guards against a paste of the wrong thing (a whole file) being
  // encrypted and stored; real provider keys are well under this.
  @IsString()
  @MinLength(1)
  @MaxLength(4096)
  value!: string;
}

export class TestApiKeyDto {
  /** Optional candidate to verify instead of the currently stored value. */
  @IsOptional()
  @IsString()
  @MaxLength(4096)
  value?: string;
}
