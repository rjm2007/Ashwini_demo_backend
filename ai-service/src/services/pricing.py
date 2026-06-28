"""Config-driven model pricing (USD)."""

from __future__ import annotations

# Rates per 1M tokens unless noted
_MODEL_RATES: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
}

_OCR_PAGE_RATE = 0.0015


def estimate_cost_usd(
    *,
    provider: str,
    model: str,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    units: float | None = None,
    unit_kind: str | None = None,
) -> float:
    if unit_kind == "page" and units:
        return round(float(units) * _OCR_PAGE_RATE, 6)
    rates = _MODEL_RATES.get(model, {"input": 0.5, "output": 1.5})
    cost = 0.0
    if input_tokens:
        cost += (input_tokens / 1_000_000) * rates["input"]
    if output_tokens:
        cost += (output_tokens / 1_000_000) * rates["output"]
    return round(cost, 6)
