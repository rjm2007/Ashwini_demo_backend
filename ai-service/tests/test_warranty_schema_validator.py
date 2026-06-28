"""Schema validator smoke tests + Planning/Schema.json golden checks."""

from __future__ import annotations

import json
from pathlib import Path

from src.services.schema_validator import validate_warranty_schema

_GOLDEN_PATH = Path(__file__).resolve().parents[3] / "Planning" / "Schema.json"


def _load_golden() -> dict:
    return json.loads(_GOLDEN_PATH.read_text(encoding="utf-8"))


def test_old_field_wrapper_fails():
    ok, errors = validate_warranty_schema({"vehicle": {}, "profiles": {}})
    assert not ok
    assert errors


def test_minimal_warranty_shape_passes_basic():
    golden = {
        "document": {
            "document_id": "TEST-001",
            "document_type": "asset_warranty_coverage_lookup",
            "source_file": "test.pdf",
        },
        "warranty_program": {"program_id": "P1", "program_name": "Test"},
        "applicability": {"make": "Volvo Truck", "models": ["VNL"]},
        "coverage_components": [
            {
                "coverage_id": "E6460",
                "coverage_name": "Engine Plan 2",
                "coverage_hierarchy": {
                    "system": "Powertrain",
                    "subsystem": "Engine",
                    "component_group": "Engine",
                    "component": "Engine Plan 2",
                },
                "coverage_type": "Engine",
                "coverage_period": {"duration_text": "48 months / 500,000 miles"},
                "confidence_score": 0.9,
            }
        ],
    }
    ok, errors = validate_warranty_schema(golden)
    assert ok, errors


def test_planning_schema_json_validates():
    if not _GOLDEN_PATH.exists():
        return
    schema = _load_golden()
    ok, errors = validate_warranty_schema(schema)
    assert ok, errors


def test_planning_schema_coverage_count():
    if not _GOLDEN_PATH.exists():
        return
    schema = _load_golden()
    rows = schema.get("coverage_components") or []
    assert 25 <= len(rows) <= 27


def test_planning_schema_spot_checks():
    if not _GOLDEN_PATH.exists():
        return
    schema = _load_golden()
    by_id = {r["coverage_id"]: r for r in schema.get("coverage_components") or []}

    e6460 = by_id["E6460"]
    assert e6460["coverage_hierarchy"]["system"] == "Powertrain"
    assert e6460["coverage_hierarchy"]["subsystem"] == "Engine"
    assert e6460["coverage_period"]["duration_months"] == 48
    assert e6460["coverage_period"]["mileage_limit"] == 500000

    et460 = by_id["ET460"]
    assert et460["coverage_hierarchy"]["system"] == "Emission"
    assert et460["coverage_period"]["duration_months"] == 48

    u065 = by_id["U065"]
    assert u065["coverage_hierarchy"]["subsystem"] == "Transmission"
    assert u065["coverage_period"]["mileage_limit"] == 750000

    z0421 = by_id["Z0421"]
    assert z0421["coverage_type"] == "Information Only"


def test_no_field_wrapper_in_golden():
    if not _GOLDEN_PATH.exists():
        return
    schema = _load_golden()
    for row in schema.get("coverage_components") or []:
        assert "status" not in row
        assert "evidence_quote" not in row
        period = row.get("coverage_period") or {}
        assert "status" not in period
