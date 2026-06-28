"""Smoke-test schema-driven chunk construction."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.schema_chunk_builder import (
    build_schema_chunks,
    build_vehicle_context,
    extract_coverage_facts,
    has_usable_schema,
)


def fw(value, status="extracted", page=1):
    return {"value": value, "status": status, "confidence": 0.9, "page": page}


master = {
    "profiles": {
        "coverage_code_table": {
            "coverage_codes": [
                {
                    "code": fw("U030"),
                    "description": fw("Frame & Crossmembers, 72 Months/750,000 Miles"),
                    "category": fw("structural"),
                    "duration": fw("72 months"),
                    "distance": fw("750,000 miles"),
                    "start_date": fw("2019-03"),
                    "end_date": fw("2025-03"),
                },
                {
                    "code": fw("U06"),
                    "description": fw("Standard Engine Warranty: 24 months/250,000 Miles"),
                    "category": fw("engine"),
                    "duration": fw("24 months"),
                    "distance": fw("250,000 miles"),
                    "start_date": fw("2019-03"),
                    "end_date": fw("2021-03"),
                },
                {
                    "code": fw(None, status="missing"),
                    "description": fw("garbage row"),
                },
            ]
        }
    }
}

metadata = {
    "make": "Volvo Truck",
    "model": "VNL64TN",
    "year": "2019",
    "vin": "4V4NC9EH3LN218364",
    "chassisId": "218364",
}

assert "4V4NC9EH3LN218364" in build_vehicle_context(metadata)
assert has_usable_schema(master)

chunks = build_schema_chunks(master, metadata, "test-doc")
coverage_chunks = [chunk for chunk in chunks if chunk["chunkType"] == "coverage_code"]
assert len(coverage_chunks) == 2
assert all(chunk["coverageCodes"] for chunk in coverage_chunks)

u030 = next(chunk for chunk in coverage_chunks if chunk["coverageCodes"] == ["U030"])
assert u030["structuredMeta"]["end_date"] == "2025-03"
assert "U030" in u030["chunkText"]
assert "garbage row" not in "\n".join(chunk["chunkText"] for chunk in coverage_chunks)

facts = extract_coverage_facts(master)
assert len(facts) == 2
assert next(fact for fact in facts if fact["code"] == "U030")["end_date"] == "2025-03"

print("schema_chunk_builder assertions passed")
