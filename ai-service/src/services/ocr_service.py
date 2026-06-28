"""Production OCR — same chain as test-rag: Textract → Docling → OpenAI Vision."""

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import boto3

from ..config import settings
from .ocr_config import load_ocr_config
from .pdf_reader import PDFReader

logger = logging.getLogger("ocr")


class OcrService:
    """
    Download PDF from S3, run PDFReader three-tier extraction, return page list.

    OCR_METHOD env: auto | textract | docling | openai_vision (same as test-rag ingest).
    """

    def __init__(self) -> None:
        self.bucket = settings.s3_bucket_name
        self.method = (settings.ocr_method or "auto").strip().lower()
        self.s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
        )
        self.reader = PDFReader(load_ocr_config())

    def run_ocr(self, s3_path: str) -> dict[str, Any]:
        """Returns {pages: [{page, text}, ...]} for a PDF at s3_path."""
        logger.info("OCR start s3_path=%s method=%s", s3_path, self.method)

        tmp_path = None
        try:
            obj = self.s3.get_object(Bucket=self.bucket, Key=s3_path)
            suffix = Path(s3_path).suffix or ".pdf"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(obj["Body"].read())
                tmp_path = tmp.name

            pages = self.reader.extract(tmp_path, method=self.method)
            if not pages:
                raise RuntimeError(
                    f"All OCR tiers failed for {s3_path} (method={self.method}). "
                    "Check AWS Textract, Docling URL, and OPENAI_API_KEY."
                )

            total_chars = sum(len(p.get("text", "")) for p in pages)
            logger.info(
                "OCR complete s3_path=%s pages=%d chars=%d method=%s",
                s3_path,
                len(pages),
                total_chars,
                self.method,
            )
            return {"pages": pages, "ocr_method": self.method}

        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
