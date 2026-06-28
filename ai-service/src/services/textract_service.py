import io
import logging
import time
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from pypdf import PdfReader

from ..config import settings

logger = logging.getLogger("ocr")


class TextractService:
    """Wraps OCR extraction. Tries AWS Textract async, then falls back to pypdf for text PDFs."""

    POLL_INTERVAL_SECONDS = 3
    POLL_TIMEOUT_SECONDS = 600  # 10 minutes

    def __init__(self) -> None:
        self.bucket = settings.s3_bucket_name
        self.s3 = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id or None,
            aws_secret_access_key=settings.aws_secret_access_key or None,
        )
        try:
            self.textract = boto3.client(
                "textract",
                region_name=settings.aws_region,
                aws_access_key_id=settings.aws_access_key_id or None,
                aws_secret_access_key=settings.aws_secret_access_key or None,
            )
        except Exception as exc:  # pragma: no cover - very rare client init error
            logger.warning("Textract client init failed: %s", exc)
            self.textract = None

    def run_ocr(self, s3_path: str) -> dict[str, Any]:
        """Returns {pages: [{page, text}, ...]} for a PDF stored at s3_path."""
        logger.info("OCR start s3_path=%s bucket=%s", s3_path, self.bucket)

        if self.textract is not None:
            try:
                pages = self._textract_async(s3_path)
                if pages:
                    logger.info("OCR via Textract ok pages=%d", len(pages))
                    return {"pages": pages}
                logger.warning("Textract returned 0 pages, falling back to pypdf")
            except (ClientError, BotoCoreError) as exc:
                logger.warning(
                    "Textract failed (%s), falling back to pypdf",
                    getattr(exc, "response", {}).get("Error", {}).get("Code", str(exc)),
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("Textract unexpected failure: %s, falling back to pypdf", exc)

        pages = self._pypdf_fallback(s3_path)
        logger.info("OCR via pypdf fallback ok pages=%d", len(pages))
        return {"pages": pages}

    def _textract_async(self, s3_path: str) -> list[dict[str, Any]]:
        """Runs Textract StartDocumentTextDetection -> GetDocumentTextDetection."""
        start = self.textract.start_document_text_detection(
            DocumentLocation={"S3Object": {"Bucket": self.bucket, "Name": s3_path}}
        )
        job_id = start["JobId"]
        logger.info("Textract job started jobId=%s s3=%s", job_id, s3_path)

        deadline = time.time() + self.POLL_TIMEOUT_SECONDS
        next_token: str | None = None
        blocks: list[dict[str, Any]] = []
        status = "IN_PROGRESS"

        while time.time() < deadline:
            kwargs: dict[str, Any] = {"JobId": job_id}
            if next_token:
                kwargs["NextToken"] = next_token
            response = self.textract.get_document_text_detection(**kwargs)
            status = response.get("JobStatus", "IN_PROGRESS")

            if status == "FAILED":
                raise RuntimeError(
                    f"Textract job {job_id} failed: {response.get('StatusMessage')}"
                )

            if status == "SUCCEEDED":
                blocks.extend(response.get("Blocks", []))
                next_token = response.get("NextToken")
                if not next_token:
                    break
                continue

            logger.info(
                "Textract job polling jobId=%s status=%s elapsed=%ds",
                job_id,
                status,
                int(self.POLL_TIMEOUT_SECONDS - (deadline - time.time())),
            )
            time.sleep(self.POLL_INTERVAL_SECONDS)

        if status != "SUCCEEDED":
            raise TimeoutError(
                f"Textract job {job_id} did not finish within {self.POLL_TIMEOUT_SECONDS}s"
            )

        pages_dict: dict[int, list[str]] = {}
        for block in blocks:
            if block.get("BlockType") != "LINE":
                continue
            page_no = block.get("Page", 1)
            pages_dict.setdefault(page_no, []).append(block.get("Text", ""))

        return [
            {"page": page_no, "text": "\n".join(lines)}
            for page_no, lines in sorted(pages_dict.items())
        ]

    def _pypdf_fallback(self, s3_path: str) -> list[dict[str, Any]]:
        """Reads PDF bytes from S3 and extracts text page-by-page using pypdf."""
        logger.info("pypdf fallback fetching s3=%s", s3_path)
        obj = self.s3.get_object(Bucket=self.bucket, Key=s3_path)
        data = obj["Body"].read()
        reader = PdfReader(io.BytesIO(data))
        pages: list[dict[str, Any]] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning("pypdf page %d extraction failed: %s", index, exc)
                text = ""
            pages.append({"page": index, "text": text})
        total_chars = sum(len(p["text"]) for p in pages)
        logger.info("pypdf fallback extracted pages=%d total_chars=%d", len(pages), total_chars)
        return pages
