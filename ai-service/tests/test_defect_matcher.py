"""Defect matcher hierarchy-first scoring tests."""

from __future__ import annotations

from src.query.defect_matcher import match_coverage_rows


def test_engine_defect_matches_e6460_not_d0001():
    rows = [
        {
            "coverage_id": "D0001",
            "coverage_name": "Engine Block",
            "coverage_hierarchy": {
                "system": "Powertrain",
                "subsystem": "Engine",
                "component_group": "Engine Components",
                "component": "Block",
            },
        },
        {
            "coverage_id": "E6460",
            "coverage_name": "Engine Plan 2",
            "coverage_hierarchy": {
                "system": "Powertrain",
                "subsystem": "Engine",
                "component_group": "Engine",
                "component": "Engine Plan 2",
            },
        },
    ]
    targets = [
        {
            "system": "Powertrain",
            "subsystem": "Engine",
            "component_group": "Engine",
            "confidence": 0.9,
        }
    ]
    matched = match_coverage_rows(rows, targets)
    assert matched
    assert matched[0]["coverage_id"] == "E6460"


def test_no_match_below_threshold():
    rows = [{"coverage_id": "Z0421", "coverage_name": "Info", "coverage_hierarchy": {"system": "Administrative"}}]
    targets = [{"system": "Powertrain", "subsystem": "Engine", "component_group": "Engine", "confidence": 0.9}]
    assert match_coverage_rows(rows, targets) == []
