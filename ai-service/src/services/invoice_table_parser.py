"""Deterministic invoice extraction from Docling table cells.

Extracts line items (Part / Description / Qty / Unit / Price / Extended) and
totals (parts_total, labor_total, core_charge, tax, grand_total) from repair
invoice tables identified by the presence of price/amount/qty/part headers.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("invoice_table_parser")

_PRICE_RE = re.compile(r"\$?\s*([\d,]+\.?\d{0,2})")


def _fw(value: Any, status: str = "extracted", page: int = 1) -> dict:
    if value in (None, ""):
        return {"value": None, "status": "missing", "confidence": 0.0, "page": page, "evidence_quote": ""}
    return {"value": value, "status": status, "confidence": 0.9, "page": page, "evidence_quote": ""}


def _page_no(item: dict) -> int | None:
    prov = item.get("prov") or []
    if prov and isinstance(prov[0], dict):
        return prov[0].get("page_no")
    return None


def _is_invoice_table(header_row: dict[int, str]) -> bool:
    texts = " ".join(header_row.values()).lower()
    return any(k in texts for k in ["price", "amount", "extended", "qty", "quantity", "part"])


def _grid(cells: list[dict]) -> dict[int, dict[int, str]]:
    grid: dict[int, dict[int, str]] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        text = (cell.get("text") or "").strip()
        if not text:
            continue
        row = int(cell.get("start_row_offset_idx", 0) or 0)
        col = int(cell.get("start_col_offset_idx", 0) or 0)
        if col in grid.get(row, {}) and len(grid[row][col]) >= len(text):
            continue
        grid.setdefault(row, {})[col] = text
    return grid


def _identify_invoice_cols(header: dict[int, str]) -> dict[str, int | None]:
    cols: dict[str, int | None] = {
        "part": None, "description": None, "qty": None,
        "unit": None, "price": None, "extended": None,
    }
    for col, text in header.items():
        low = text.lower()
        if "part" in low or "supp" in low:
            cols["part"] = col
        elif "description" in low or "desc" in low or "ref" in low:
            cols["description"] = col
        elif "qty" in low or "quantity" in low:
            cols["qty"] = col
        elif "u/m" in low or "unit" in low:
            cols["unit"] = col
        elif "extended" in low or "ext" in low:
            cols["extended"] = col
        elif "price" in low or "amount" in low:
            cols["price"] = col
    return cols


def parse_invoice_from_tables(tables: list[dict]) -> dict:
    """Return dict with line_items[] and totals{} from Docling invoice tables."""
    line_items: list[dict] = []
    totals: dict[str, Any] = {}

    for tbl in tables or []:
        if not isinstance(tbl, dict):
            continue
        page = _page_no(tbl) or 1
        data = tbl.get("data") or {}
        cells = (data.get("table_cells") or []) if isinstance(data, dict) else []
        if not cells:
            continue
        grid = _grid(cells)
        if not grid:
            continue
        header_row = grid.get(min(grid.keys()), {})
        if not _is_invoice_table(header_row):
            continue
        cols = _identify_invoice_cols(header_row)

        for row_idx in sorted(grid)[1:]:
            row = grid[row_idx]
            part = (row.get(cols["part"]) or "").strip() if cols["part"] is not None else ""
            desc = (row.get(cols["description"]) or "").strip() if cols["description"] is not None else ""
            qty = (row.get(cols["qty"]) or "").strip() if cols["qty"] is not None else ""
            unit = (row.get(cols["unit"]) or "").strip() if cols["unit"] is not None else ""
            price = (row.get(cols["price"]) or "").strip() if cols["price"] is not None else ""
            ext = (row.get(cols["extended"]) or "").strip() if cols["extended"] is not None else ""

            if not part and desc:
                dl = desc.lower()
                pm = _PRICE_RE.search(ext or price or "")
                val = pm.group(1).replace(",", "") if pm else None
                if "total part" in dl and val:
                    totals["parts_total"] = _fw(val, page=page)
                elif "total labor" in dl and val:
                    totals["labor_total"] = _fw(val, page=page)
                elif "core" in dl and val:
                    totals["core_charge"] = _fw(val, page=page)
                elif ("ehc" in dl or "environmental" in dl) and val:
                    totals["ehc"] = _fw(val, page=page)
                elif ("grand" in dl or "total invoice" in dl) and val:
                    totals["grand_total"] = _fw(val, page=page)
                continue

            if not (part or desc):
                continue

            line_items.append({
                "part_no": _fw(part or None, page=page),
                "description": _fw(desc or None, page=page),
                "quantity": _fw(qty or None, page=page),
                "unit": _fw(unit or None, page=page),
                "unit_price": _fw(price or None, page=page),
                "extended_price": _fw(ext or None, page=page),
            })

    logger.info("invoice_table_parser: %d line items, totals=%s", len(line_items), list(totals))
    return {"line_items": line_items, "totals": totals}
