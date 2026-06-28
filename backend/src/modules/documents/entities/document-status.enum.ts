export enum DocumentRepository {
  PENDING_REVIEW = "pending_review",
  REVIEWER_APPROVED = "reviewer_approved",
  CERTIFIED = "certified",
  REJECTED = "rejected",
  ARCHIVED = "archived"
}

export enum ProcessingStatus {
  UPLOADED = "uploaded",
  OCR_IN_PROGRESS = "ocr_in_progress",
  OCR_COMPLETE = "ocr_complete",
  EXTRACTION_IN_PROGRESS = "extraction_in_progress",
  EXTRACTION_COMPLETE = "extraction_complete",
  EMBEDDED = "embedded",
  READY_FOR_REVIEW = "ready_for_review",
  FAILED = "failed",
  PARSING = "parsing",
  STRUCTURING = "structuring",
  CLASSIFYING = "classifying",
  AWAITING_CERTIFICATION = "awaiting_certification",
  SCHEMA_EXTRACTION = "schema_extraction",
  EMBEDDING = "embedding",
  PROCESSING_COMPLETE = "processing_complete"
}
