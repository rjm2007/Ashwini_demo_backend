"""Query mode detection for Phase 2 reasoning paths."""

from __future__ import annotations

import re

_HALLUCINATION_PROBE_RE = re.compile(
    r"\b("
    r"does (this|the) document mention|is .+ included|is .+ covered|"
    r"phone number|deductible|roadside|windshield|battery|tire warranty|"
    r"accidental damage|customer service|reimbursement amount"
    r")\b",
    re.IGNORECASE,
)


def is_hallucination_probe(question: str) -> bool:
    """Level-5 style yes/no on absent topics — use strict evidence-only mode."""
    return bool(_HALLUCINATION_PROBE_RE.search(question or ""))
