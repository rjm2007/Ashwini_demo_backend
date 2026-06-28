"""Heuristic classify enrichment tests."""

from __future__ import annotations

from src.services.coverage_classify_heuristic import heuristic_classify_row


def test_e6460_classifies_as_engine():
    row = {
        "coverage_id": "E6460",
        "coverage_name_raw": "ENGINEPLAN2:48MONTHS/600KMILES-VEHICLEWARRANTYCLAIMJOB (DC27)",
        "coverage_name": "E6460",
    }
    out = heuristic_classify_row(row)
    assert out["coverage_type"] == "Engine"
    assert out["coverage_hierarchy"]["system"] == "Powertrain"
    assert out["coverage_hierarchy"]["subsystem"] == "Engine"


def test_d0002_classifies_as_hvac():
    row = {
        "coverage_id": "D0002",
        "coverage_name_raw": "AC Sealed(Parts touched by Freon).12Months/Unlimited Mieage",
        "coverage_name": "D0002",
    }
    out = heuristic_classify_row(row)
    assert out["coverage_type"] == "HVAC"
