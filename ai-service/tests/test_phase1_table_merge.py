"""Smoke-test merging Docling tables[] into pages_text."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.services.docling_structure_service import _build_pages_text_with_tables


def cell(text, row, col):
    return {"text": text, "start_row_offset_idx": row, "start_col_offset_idx": col}


docling_response = {
    "document": {
        "json_content": {
            "texts": [
                {"text": "Vehicle Data Administration", "prov": [{"page_no": 1}]},
                {"text": "Coverage Information", "prov": [{"page_no": 1}]},
                {"text": "VIN 4V4NC9EH3LN218364", "prov": [{"page_no": 1}]},
            ],
            "tables": [
                {
                    "prov": [{"page_no": 1}],
                    "data": {
                        "table_cells": [
                            cell("Coverage", 0, 0),
                            cell("Description", 0, 1),
                            cell("Start", 0, 2),
                            cell("End", 0, 3),
                            cell("U030", 1, 0),
                            cell("Frame & Crossmembers", 1, 1),
                            cell("2019-03", 1, 2),
                            cell("2025-03", 1, 3),
                            cell("U06", 2, 0),
                            cell("Standard Engine Warranty", 2, 1),
                            cell("2019-03", 2, 2),
                            cell("2021-03", 2, 3),
                        ]
                    },
                }
            ],
        }
    }
}

pages = _build_pages_text_with_tables(docling_response)
assert len(pages) == 1
assert "VIN 4V4NC9EH3LN218364" in pages[0]["text"]
assert "U030 | Frame & Crossmembers | 2019-03 | 2025-03" in pages[0]["text"]
assert "U06 | Standard Engine Warranty | 2019-03 | 2021-03" in pages[0]["text"]

print("phase1 table merge assertions passed")
