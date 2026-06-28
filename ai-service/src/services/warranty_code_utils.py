"""Warranty code extraction and query enrichment for hybrid retrieval."""

from __future__ import annotations

import re

# Coverage / claim codes common in Volvo export PDFs
_CODE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bU\d{2,4}[A-Z]?\b", re.IGNORECASE),
    re.compile(r"\bD\d{3,4}\b", re.IGNORECASE),
    re.compile(r"\bET\d{2,4}\b", re.IGNORECASE),
    re.compile(r"\bE\d{3,4}\b", re.IGNORECASE),
    re.compile(r"\bG\d{2,3}\b", re.IGNORECASE),
    re.compile(r"\bHAC\d{1,3}\b", re.IGNORECASE),
    re.compile(r"\bTOW\d+\b", re.IGNORECASE),
    re.compile(r"\bZ\d{3,4}\b", re.IGNORECASE),
    re.compile(r"\bEPA\d+\b", re.IGNORECASE),
]

# Symptom / topic hints → extra BM25 + lexical boost terms
SYMPTOM_HINTS: dict[str, list[str]] = {
    "transmission": ["TOW2", "TOW4", "transmission", "driveline"],
    "tow": ["TOW2", "TOW4"],
    "engine": ["U030", "U050", "engine", "powertrain"],
    "epa": ["EPA17", "emission", "U06A", "U06B"],
    "emission": ["EPA17", "U06B", "emission"],
    "driveline": ["U050", "driveline"],
    "turbo": ["turbocharger", "turbo"],
    # --- added: engine sub-components fold into the engine assembly coverage ---
    "fuel rail": ["U06", "U06A", "engine", "fuel system"],
    "fuel pressure": ["U06", "U06A", "engine", "fuel system"],
    "fuel injector": ["U06", "U06A", "engine", "fuel system"],
    "injector": ["U06", "U06A", "engine"],
    "fuel pump": ["U06", "U06A", "engine", "fuel system"],
    "egr": ["U06B", "EPA17", "emission"],
    "aftertreatment": ["ET460", "U13", "emission"],
    "dpf": ["ET460", "U13", "emission"],
    "water pump": ["U06", "U06A", "engine"],
    "alternator": ["U06", "engine"],
}

# When OCR omits a label but related rows exist (e.g. EPA17 → U06A / GHG text)
CODE_ALIASES: dict[str, list[str]] = {
    "EPA17": ["U06A", "U06B", "GHG", "emission", "EPA"],
}


def extract_warranty_codes(text: str) -> list[str]:
    """Pull warranty codes from free text (question, rewrite, chunk)."""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for pattern in _CODE_PATTERNS:
        for match in pattern.finditer(text):
            code = match.group(0).upper()
            if code not in seen:
                seen.add(code)
                found.append(code)
    return found


def _symptom_hints(question: str) -> list[str]:
    q = (question or "").lower()
    hints: list[str] = []
    seen: set[str] = set()
    for key, terms in SYMPTOM_HINTS.items():
        if key in q:
            for term in terms:
                norm = term.upper() if re.match(r"^[A-Z0-9]+$", term, re.I) else term
                token_key = str(norm).upper()
                if token_key not in seen:
                    seen.add(token_key)
                    hints.append(norm)
    return hints


def enrich_metadata_with_codes(metadata: dict, question: str) -> dict:
    """Merge regex-extracted codes and symptom hints into metadata for retrieval."""
    codes: list[str] = []
    seen: set[str] = set()

    def _add(items: list[str]) -> None:
        for item in items:
            norm = item.upper() if re.match(r"^[A-Z0-9]+$", item, re.I) else item
            key = str(norm).upper()
            if key not in seen:
                seen.add(key)
                codes.append(norm)

    _add(extract_warranty_codes(question))
    _add(extract_warranty_codes(metadata.get("rewritten_query") or ""))
    _add(_symptom_hints(question))
    for code in list(codes):
        for alias in CODE_ALIASES.get(code, []):
            _add([alias])

    keywords: list[str] = list(metadata.get("semantic_keywords") or [])
    kw_seen = {k.lower() for k in keywords}
    for code in codes:
        token = code if isinstance(code, str) else str(code)
        if token.lower() not in kw_seen:
            keywords.append(token)
            kw_seen.add(token.lower())

    metadata["semantic_keywords"] = keywords[:12]
    metadata["warranty_codes"] = codes
    return metadata
