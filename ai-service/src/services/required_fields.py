"""Single source of truth for the required-fields gate — used by vehicle_fallback,
schema_extraction, pipeline_orchestrator, and mirrored in the TS admin-approve gate.

Rules (matching the admin-approve gate in review.service.ts):
  - make always required
  - model required EXCEPT for coverage_code_table
"""

from __future__ import annotations


def has_required_fields(
    vin: str | None,
    chassis: str | None,
    make: str | None,
    model: str | None,
    document_type: str = "",
    unit_number: str | None = None,
) -> bool:
    if not make:
        return False
    if document_type == "coverage_code_table":
        return True
    return bool(model)
