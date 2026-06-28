"""Validate extracted warranty schema against warranty_schema.json."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("schema_validator")

_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "warranty_schema.json"
_SCHEMA: dict | None = None


def _load_schema() -> dict:
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return _SCHEMA


def validate_warranty_schema(data: dict) -> tuple[bool, list[str]]:
    """Return (ok, errors). Uses jsonschema if available, else required-key check."""
    errors: list[str] = []
    for key in ("document", "warranty_program", "applicability", "coverage_components"):
        if key not in data:
            errors.append(f"missing required key: {key}")
    if not isinstance(data.get("coverage_components"), list):
        errors.append("coverage_components must be an array")
    elif len(data.get("coverage_components") or []) == 0:
        errors.append("coverage_components is empty")

    try:
        import jsonschema

        jsonschema.validate(instance=data, schema=_load_schema())
    except ImportError:
        logger.warning("jsonschema not installed; using basic validation only")
    except Exception as exc:
        errors.append(str(exc))

    return len(errors) == 0, errors
