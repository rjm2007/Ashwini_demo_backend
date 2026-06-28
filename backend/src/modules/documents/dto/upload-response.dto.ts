import { ProcessingStatus } from "../entities/document-status.enum";

export class UploadResponseDto {
  documentId!: string;
  filename!: string;
  status!: ProcessingStatus;
  message!: string;
}
