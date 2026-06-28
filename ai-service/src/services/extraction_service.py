import json
from pathlib import Path
from .llm_service import LlmService


class ExtractionService:
    """This class extracts structured metadata from OCR text."""

    def __init__(self) -> None:
        self.llm = LlmService()
        self.prompt = Path("src/prompts/metadata_extraction.txt").read_text(encoding="utf-8")

    def extract_metadata(self, text: str) -> dict:
        """This function asks small model for strict JSON metadata extraction."""
        safe_text = text.replace("{", "\\{").replace("}", "\\}")
        output = self.llm.small_model_call(
            prompt=f"{self.prompt}\n\nDocument text:\n{safe_text}",
            system_message="Extract metadata safely.",
        )
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return {
                "make": None,
                "model": None,
                "year": None,
                "warranty_type": None,
                "country": None,
                "coverage_period": None,
                "coverage_components": [],
                "exclusions": [],
            }
