"""OCR settings adapter (shared by pdf_reader and pipeline)."""

from dataclasses import dataclass

from ..config import settings


@dataclass
class OcrConfig:
    aws_region: str
    aws_access_key_id: str
    aws_secret_access_key: str
    s3_bucket: str
    openai_api_key: str
    small_model: str
    docling_url: str
    textract_poll_interval: int = 3
    textract_timeout: int = 600


def load_ocr_config() -> OcrConfig:
    return OcrConfig(
        aws_region=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
        s3_bucket=settings.s3_bucket_name,
        openai_api_key=settings.openai_api_key,
        small_model=settings.small_model,
        docling_url=settings.docling_serve_url or settings.docling_url,
        textract_poll_interval=settings.textract_poll_interval,
        textract_timeout=settings.textract_timeout,
    )
