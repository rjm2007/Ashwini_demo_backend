export class QueryResponseDto {
  answer!: string;
  evidence!: unknown[];
  confidenceScore!: number;
  metadataFiltersApplied!: Record<string, unknown>;
}
