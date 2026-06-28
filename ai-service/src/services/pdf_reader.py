"""
pdf_reader.py — Three-tier PDF text extraction with automatic fallback.

Extraction chain (tries in order, falls back on failure):
  1. AWS Textract   — Best quality for scanned docs. Needs AWS creds + S3 bucket.
  2. Docling Docker — Calls the self-hosted docling-service container via REST API.
                      No local install needed. Run: docker compose up docling
  3. OpenAI Vision  — Renders pages to images, sends to GPT-4o-mini vision.
                      Expensive but always available if you have an OpenAI key.

Each tier returns the same format: [{"page": 1, "text": "..."}, ...]

Usage:
    from pdf_reader import PDFReader
    reader = PDFReader(cfg)
    pages = reader.extract("warranty.pdf")
    # pages = [{"page": 1, "text": "..."}, {"page": 2, "text": "..."}, ...]
"""

import base64
import logging
import time
from pathlib import Path

import httpx

from .ocr_config import OcrConfig
from .openai_compat import chat_create_kwargs

logger = logging.getLogger("pdf_reader")


class PDFReader:
    """
    Smart PDF text extractor with three-tier fallback.

    Tries Textract → Docling (Docker REST) → OpenAI Vision in order.
    You can also force a specific tier via the `method` parameter.
    """

    def __init__(self, cfg: OcrConfig):
        self.cfg = cfg

    def extract(self, pdf_path: str, method: str = "auto") -> list[dict]:
        """
        Extract per-page text from a PDF.

        Args:
            pdf_path: Local path to PDF file
            method: "auto" (fallback chain), "textract", "docling", "openai_vision"

        Returns:
            [{"page": 1, "text": "..."}, ...]
        """
        pdf_path = str(Path(pdf_path).resolve())
        logger.info("PDFReader.extract(%s, method=%s)", Path(pdf_path).name, method)

        if method == "textract":
            return self._try_textract(pdf_path)
        elif method == "docling":
            return self._try_docling(pdf_path)
        elif method == "openai_vision":
            return self._try_openai_vision(pdf_path)

        # Auto: try each tier in order
        # ── Tier 1: AWS Textract ────────────────────────────────
        if self.cfg.aws_access_key_id and self.cfg.s3_bucket:
            try:
                pages = self._try_textract(pdf_path)
                if self._has_useful_text(pages):
                    logger.info("Tier 1 (Textract) succeeded: %d pages", len(pages))
                    return pages
                logger.warning("Tier 1 (Textract) returned no useful text, trying Tier 2")
            except Exception as e:
                logger.warning("Tier 1 (Textract) failed: %s — trying Tier 2", e)
        else:
            logger.info("Tier 1 (Textract) skipped: no AWS credentials configured")

        # ── Tier 2: Docling Docker REST API ─────────────────────
        try:
            pages = self._try_docling(pdf_path)
            if self._has_useful_text(pages):
                logger.info("Tier 2 (Docling Docker) succeeded: %d pages", len(pages))
                return pages
            logger.warning("Tier 2 (Docling Docker) returned no useful text, trying Tier 3")
        except Exception as e:
            logger.warning("Tier 2 (Docling Docker) failed: %s — trying Tier 3", e)

        # ── Tier 3: OpenAI Vision ───────────────────────────────
        if self.cfg.openai_api_key:
            try:
                pages = self._try_openai_vision(pdf_path)
                if self._has_useful_text(pages):
                    logger.info("Tier 3 (OpenAI Vision) succeeded: %d pages", len(pages))
                    return pages
            except Exception as e:
                logger.error("Tier 3 (OpenAI Vision) failed: %s", e)

        logger.error("All extraction tiers failed for %s", pdf_path)
        return []

    # ════════════════════════════════════════════════════════════
    # Tier 1: AWS Textract
    # ════════════════════════════════════════════════════════════

    def _try_textract(self, pdf_path: str) -> list[dict]:
        """Upload to S3, run Textract async, return per-page text."""
        import boto3

        s3 = boto3.client(
            "s3",
            region_name=self.cfg.aws_region,
            aws_access_key_id=self.cfg.aws_access_key_id,
            aws_secret_access_key=self.cfg.aws_secret_access_key,
        )
        textract = boto3.client(
            "textract",
            region_name=self.cfg.aws_region,
            aws_access_key_id=self.cfg.aws_access_key_id,
            aws_secret_access_key=self.cfg.aws_secret_access_key,
        )

        filename = Path(pdf_path).name
        s3_key = f"ocr-temp/{filename}"

        # Upload
        logger.info("  [Textract] Uploading to s3://%s/%s", self.cfg.s3_bucket, s3_key)
        s3.upload_file(pdf_path, self.cfg.s3_bucket, s3_key)

        try:
            # Start async job
            start = textract.start_document_text_detection(
                DocumentLocation={"S3Object": {"Bucket": self.cfg.s3_bucket, "Name": s3_key}}
            )
            job_id = start["JobId"]
            logger.info("  [Textract] Job started: %s", job_id)

            # Poll
            deadline = time.time() + self.cfg.textract_timeout
            blocks: list[dict] = []
            status = "IN_PROGRESS"
            while time.time() < deadline:
                resp = textract.get_document_text_detection(JobId=job_id)
                status = resp.get("JobStatus", "IN_PROGRESS")

                if status == "FAILED":
                    raise RuntimeError(f"Textract FAILED: {resp.get('StatusMessage')}")

                if status == "SUCCEEDED":
                    blocks.extend(resp.get("Blocks", []))
                    next_token = resp.get("NextToken")
                    while next_token:
                        resp = textract.get_document_text_detection(
                            JobId=job_id, NextToken=next_token
                        )
                        blocks.extend(resp.get("Blocks", []))
                        next_token = resp.get("NextToken")
                    break

                time.sleep(self.cfg.textract_poll_interval)

            if status != "SUCCEEDED":
                raise TimeoutError(f"Textract timed out after {self.cfg.textract_timeout}s")

            # Group LINE blocks by page
            pages_dict: dict[int, list[str]] = {}
            for block in blocks:
                if block.get("BlockType") != "LINE":
                    continue
                pg = block.get("Page", 1)
                pages_dict.setdefault(pg, []).append(block.get("Text", ""))

            return [
                {"page": pg, "text": "\n".join(lines)}
                for pg, lines in sorted(pages_dict.items())
            ]

        finally:
            # Cleanup temp S3 file
            try:
                s3.delete_object(Bucket=self.cfg.s3_bucket, Key=s3_key)
            except Exception:
                pass

    # ════════════════════════════════════════════════════════════
    # Tier 2: Docling Docker REST API
    # ════════════════════════════════════════════════════════════

    def _try_docling(self, pdf_path: str) -> list[dict]:
        """
        Call the self-hosted Docling Docker service via REST API.

        The docling-service container exposes:
          POST /convert  — accepts multipart PDF upload, returns per-page text JSON

        Start it with:
          docker compose up docling  (if added to main docker-compose.yml)
          OR
          cd docling-service && docker build -t docling-api . && docker run -p 5001:5001 docling-api
        """
        docling_url = self.cfg.docling_url.rstrip("/")
        convert_url = f"{docling_url}/convert"

        logger.info("  [Docling Docker] Calling %s for %s", convert_url, Path(pdf_path).name)

        # First check if the service is reachable
        try:
            health_resp = httpx.get(f"{docling_url}/health", timeout=5.0)
            if health_resp.status_code != 200:
                raise RuntimeError(f"Docling service unhealthy: status {health_resp.status_code}")
            logger.info("  [Docling Docker] Service is healthy")
        except httpx.ConnectError:
            raise RuntimeError(
                f"Docling service not reachable at {docling_url}. "
                "Start it with: docker compose up docling"
            )
        except httpx.TimeoutException:
            raise RuntimeError(f"Docling service timed out at {docling_url}")

        # Send the PDF file for conversion
        # Timeout is generous because large PDFs can take 30-60s
        with open(pdf_path, "rb") as f:
            files = {"file": (Path(pdf_path).name, f, "application/pdf")}
            resp = httpx.post(convert_url, files=files, timeout=300.0)

        if resp.status_code != 200:
            error_detail = resp.text[:500]
            raise RuntimeError(
                f"Docling conversion failed (HTTP {resp.status_code}): {error_detail}"
            )

        data = resp.json()
        pages = data.get("pages", [])
        total_chars = data.get("total_chars", sum(len(p.get("text", "")) for p in pages))

        logger.info(
            "  [Docling Docker] Extracted %d pages, %d chars in %.1fs",
            len(pages), total_chars, data.get("elapsed_seconds", 0),
        )

        return pages

    # ════════════════════════════════════════════════════════════
    # Tier 3: OpenAI Vision (render pages → GPT-4o-mini vision)
    # ════════════════════════════════════════════════════════════

    def _try_openai_vision(self, pdf_path: str) -> list[dict]:
        """
        Render each PDF page to an image, send to OpenAI Vision API.
        Uses pymupdf (fitz) for rendering and GPT-4o-mini for OCR.

        This is the most expensive tier but works on any PDF.
        """
        try:
            import fitz  # pymupdf
        except ImportError:
            raise RuntimeError("pymupdf not installed. Run: pip install pymupdf")

        from openai import OpenAI

        client = OpenAI(api_key=self.cfg.openai_api_key)
        doc = fitz.open(pdf_path)
        pages: list[dict] = []

        logger.info("  [OpenAI Vision] Processing %d pages from %s",
                     len(doc), Path(pdf_path).name)

        for page_idx in range(len(doc)):
            page = doc[page_idx]
            # Render page to PNG at 200 DPI (good balance of quality vs size)
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            b64_image = base64.b64encode(img_bytes).decode("utf-8")

            logger.info("  [OpenAI Vision] Page %d/%d (%.1f KB image)",
                         page_idx + 1, len(doc), len(img_bytes) / 1024)

            try:
                resp = client.chat.completions.create(
                    model=self.cfg.small_model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an OCR engine. Extract ALL text from this document "
                                "page image. Preserve the structure: headings, paragraphs, "
                                "table rows (use | separators for tables), list items. "
                                "Output the raw text only, no commentary."
                            ),
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/png;base64,{b64_image}",
                                        "detail": "high",
                                    },
                                },
                                {
                                    "type": "text",
                                    "text": "Extract all text from this warranty document page. Preserve tables and structure.",
                                },
                            ],
                        },
                    ],
                    **chat_create_kwargs(self.cfg.small_model, 4000),
                )
                text = resp.choices[0].message.content or ""
                pages.append({"page": page_idx + 1, "text": text.strip()})

            except Exception as e:
                logger.warning("  [OpenAI Vision] Page %d failed: %s", page_idx + 1, e)
                pages.append({"page": page_idx + 1, "text": ""})

        doc.close()
        total = sum(len(p["text"]) for p in pages)
        logger.info("  [OpenAI Vision] Done: %d pages, %d chars", len(pages), total)
        return pages

    # ════════════════════════════════════════════════════════════
    # Helpers
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _has_useful_text(pages: list[dict], min_chars: int = 30) -> bool:
        """Check if extracted pages contain enough text to be useful."""
        total = sum(len(p.get("text", "")) for p in pages)
        return total >= min_chars
