"""Deterministic coverage row classification fallback (no LLM/DB deps)."""

from __future__ import annotations

import re


def heuristic_classify_row(row: dict) -> dict:
    code = str(row.get("coverage_id") or "").upper()
    raw = str(
        row.get("coverage_name_raw")
        or (row.get("source_reference") or {}).get("text_reference")
        or row.get("coverage_name")
        or ""
    )
    raw_up = raw.upper()
    name = str(row.get("coverage_name") or code)

    if code.startswith("Z") or "INFO ONLY" in raw_up:
        return {
            "coverage_name": name,
            "coverage_type": "Information Only",
            "coverage_hierarchy": {
                "system": "Administrative",
                "subsystem": "Information Only",
                "component_group": "Info Only",
                "component": "No Claims",
            },
        }
    if code.startswith("TOW"):
        return {
            "coverage_name": name,
            "coverage_type": "Towing",
            "coverage_hierarchy": {
                "system": "Chassis",
                "subsystem": "Towing",
                "component_group": "Towing",
                "component": name,
            },
        }
    if code.startswith("HAC") or ("AC" in raw_up and "FREON" in raw_up):
        return {
            "coverage_name": name,
            "coverage_type": "HVAC",
            "coverage_hierarchy": {
                "system": "HVAC",
                "subsystem": "Air Conditioning",
                "component_group": "AC System",
                "component": name,
            },
        }
    if code.startswith("D"):
        if any(k in raw_up for k in ("AC ", "FREON", "SEALED", "HVAC")):
            h = {"system": "HVAC", "subsystem": "Air Conditioning", "component_group": "AC System", "component": name}
            return {"coverage_name": name, "coverage_type": "HVAC", "coverage_hierarchy": h}
        if "BRAKE" in raw_up:
            h = {"system": "Chassis", "subsystem": "Brakes", "component_group": "Brakes", "component": name}
            return {"coverage_name": name, "coverage_type": "Chassis", "coverage_hierarchy": h}
        if "FRAME" in raw_up or "RAIL" in raw_up:
            h = {"system": "Chassis", "subsystem": "Frame", "component_group": "Frame & Crossmembers", "component": name}
            return {"coverage_name": name, "coverage_type": "Structural", "coverage_hierarchy": h}
        if "PAINT" in raw_up:
            h = {"system": "Cab", "subsystem": "Body", "component_group": "Paint", "component": name}
            return {"coverage_name": name, "coverage_type": "Cab", "coverage_hierarchy": h}
        if "STEERING" in raw_up:
            h = {"system": "Chassis", "subsystem": "Steering", "component_group": "Steering", "component": name}
            return {"coverage_name": name, "coverage_type": "Chassis", "coverage_hierarchy": h}
        h = {"system": "Powertrain", "subsystem": "Engine", "component_group": "Engine Components", "component": name}
        return {"coverage_name": name, "coverage_type": "Engine", "coverage_hierarchy": h}
    if code.startswith("E") or code.startswith("ET"):
        if "ENGINE" in raw_up or re.match(r"E[T]?6", code):
            h = {"system": "Powertrain", "subsystem": "Engine", "component_group": "Engine", "component": name}
            return {"coverage_name": name, "coverage_type": "Engine", "coverage_hierarchy": h}
        h = {"system": "Emission", "subsystem": "Aftertreatment", "component_group": "Aftertreatment", "component": name}
        return {"coverage_name": name, "coverage_type": "Emission", "coverage_hierarchy": h}
    if code in ("U065", "U0650") or "TRANSMISSION" in raw_up or "AMT" in raw_up:
        h = {"system": "Powertrain", "subsystem": "Transmission", "component_group": "Transmission", "component": name}
        return {"coverage_name": name, "coverage_type": "Transmission", "coverage_hierarchy": h}
    if code.startswith("U05") or "DRIVELINE" in raw_up or "AXLE" in raw_up:
        h = {"system": "Powertrain", "subsystem": "Driveline", "component_group": "Driveline", "component": name}
        return {"coverage_name": name, "coverage_type": "Driveline", "coverage_hierarchy": h}
    if code == "U030" or "FRAME" in raw_up:
        h = {"system": "Chassis", "subsystem": "Frame", "component_group": "Frame & Crossmembers", "component": name}
        return {"coverage_name": name, "coverage_type": "Structural", "coverage_hierarchy": h}
    if code.startswith("U06") or code == "U06":
        h = {"system": "Powertrain", "subsystem": "Engine", "component_group": "Engine", "component": name}
        return {"coverage_name": name, "coverage_type": "Engine", "coverage_hierarchy": h}
    if code in ("U071", "U092") or "CAB" in raw_up:
        h = {"system": "Cab", "subsystem": "Cab Structure", "component_group": "Cab", "component": name}
        return {"coverage_name": name, "coverage_type": "Cab", "coverage_hierarchy": h}
    h = {"system": "Basic", "subsystem": None, "component_group": None, "component": name}
    return {"coverage_name": name, "coverage_type": "Basic", "coverage_hierarchy": h}
