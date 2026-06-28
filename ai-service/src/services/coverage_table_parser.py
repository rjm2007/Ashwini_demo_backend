"""Deterministic coverage-code extraction from Docling table cells."""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("coverage_table_parser")

CODE_RE = re.compile(
    r"^(U\d{2,4}[A-Z]?|D\d{3,4}|ET\d{2,4}|E\d{3,4}|G\d{2,3}|HAC\d{1,3}|TOW\d+|Z\d{3,4})$",
    re.IGNORECASE,
)
_CODE_TOKEN_RE = re.compile(
    r"\b(U\d{2,4}[A-Z]?|D\d{3,4}|ET\d{2,4}|E\d{3,4}|G\d{2,3}|HAC\d{1,3}|TOW\d+|Z\d{3,4})\b",
    re.IGNORECASE,
)
_OCR_CODE_FIXES = {
    "UOG": "U06A",
}

_DURATION_RE = re.compile(r"(\d+)\s*(?:months?|mo)\b", re.IGNORECASE)
_MILES_RE = re.compile(r"([\d,]+|\d+\s*K)\s*(?:miles?|mi)\b", re.IGNORECASE)
_KM_RE = re.compile(r"([\d,]+)\s*km\b", re.IGNORECASE)

_PLACEHOLDER_DATE_RE = re.compile(r"^0{2,4}[-/]?0{2}([-/]0{2,4})?$")


def _fw(value: Any, status: str = "extracted", page: int = 1, conf: float = 0.95) -> dict:
    if value in (None, ""):
        return {
            "value": None,
            "status": "missing",
            "confidence": 0.0,
            "page": page,
            "evidence_quote": "",
        }
    return {
        "value": value,
        "status": status,
        "confidence": conf,
        "page": page,
        "evidence_quote": "",
    }


def _page_no(item: dict) -> int | None:
    prov = item.get("prov") or []
    if prov and isinstance(prov[0], dict):
        return prov[0].get("page_no")
    return None


def _normalize_code_token(token: str) -> str | None:
    t = (token or "").strip().upper()
    if not t:
        return None
    t = _OCR_CODE_FIXES.get(t, t)
    return t if CODE_RE.match(t) else None


def _extract_codes(*texts: str) -> list[str]:
    """Pull all warranty code tokens from one or more text fields (OCR-tolerant)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for text in texts:
        if not text:
            continue
        normalized = text.upper().replace("UOG", "U06A")
        for token in re.split(r"[\s|]+", normalized):
            code = _normalize_code_token(token)
            if code and code not in seen:
                seen.add(code)
                ordered.append(code)
        for match in _CODE_TOKEN_RE.finditer(normalized):
            code = _normalize_code_token(match.group(1))
            if code and code not in seen:
                seen.add(code)
                ordered.append(code)
    return ordered


def _make_entry(code: str, desc_raw: str, start_raw: str, end_raw: str, page: int = 1) -> dict:
    duration, distance = _parse_duration_distance(desc_raw)
    start_val, start_status = _date_value(start_raw)
    end_val, end_status = reconcile_end_date(start_raw, duration, end_raw)
    return {
        "code": _fw(code.upper(), page=page),
        "description": _fw(desc_raw, page=page),
        "category": _fw(_category_for(code), page=page),
        "duration": _fw(duration, page=page) if duration else _fw(None),
        "distance": _fw(distance, page=page) if distance else _fw(None),
        "start_date": _fw(start_val, status=start_status, page=page) if start_val else _fw(None),
        "end_date": _fw(end_val, status=end_status, page=page) if end_val else _fw(None),
    }


def _category_for(code: str) -> str:
    c = code.upper()
    if c.startswith("D"):
        return "engine"
    if c.startswith("ET") or c.startswith("E"):
        return "emissions"
    if c.startswith("G"):
        return "other"
    if c.startswith("HAC"):
        return "hvac"
    if c.startswith("TOW"):
        return "towing"
    if c.startswith("Z"):
        return "info_only"
    if c == "U030":
        return "structural"
    if c in ("U065", "U0650"):
        return "transmission"
    if c in ("U071", "U092"):
        return "cab"
    if c in ("U13", "U15"):
        return "emissions"
    if c.startswith("U05"):
        return "driveline"
    if c in ("U04", "U06", "U06A", "U06B") or c.startswith("U06"):
        return "engine"
    return "other"


def _parse_duration_distance(description: str) -> tuple[str, str]:
    duration = ""
    distance = ""
    match = _DURATION_RE.search(description)
    if match:
        duration = f"{match.group(1)} months"
    miles = _MILES_RE.search(description)
    km = _KM_RE.search(description)
    dist_parts = []
    if miles:
        dist_parts.append(f"{miles.group(1).strip()} miles")
    if km:
        dist_parts.append(f"{km.group(1)} km")
    distance = " / ".join(dist_parts)
    return duration, distance


def _date_value(raw: str) -> tuple[str | None, str]:
    text = (raw or "").strip()
    if not text:
        return None, "missing"
    if _PLACEHOLDER_DATE_RE.match(text.replace(" ", "")):
        return text, "low_confidence"
    return text, "extracted"


def _parse_ym(s: str) -> tuple[int, int] | None:
    """Parse 'YYYY-MM' or 'YYYY-MM-DD' → (year, month) or None.

    Tolerates OCR noise in the day component (e.g. '2026~ 03-21')."""
    if not s:
        return None
    match = re.match(r"(\d{4})\D{0,3}(\d{2})", s.strip())
    return (int(match.group(1)), int(match.group(2))) if match else None


def _add_months(year: int, month: int, add: int) -> tuple[int, int]:
    total = (year * 12 + (month - 1)) + add
    return total // 12, (total % 12) + 1


def reconcile_end_date(start_raw: str, duration_text: str, ocr_end_raw: str) -> tuple[str | None, str]:
    """Return (end_value, status).

    Strategy:
      1. If start + duration are available, compute the expected end month.
      2. If OCR end agrees within 1 month, trust OCR (keeps the day component).
      3. If they disagree by > 1 month, the OCR cell is likely corrupt — use computed.
      4. If no start/duration, fall back to OCR as-is.

    Self-corrects the VDA+ stacked-date OCR error where 2025 is read as 2026.
    """
    start = _parse_ym(start_raw)
    dur = _DURATION_RE.search(duration_text or "")
    ocr = _parse_ym(ocr_end_raw)

    if not (start and dur):
        return (ocr_end_raw or None), ("extracted" if ocr_end_raw else "missing")

    months = int(dur.group(1))
    cy, cm = _add_months(start[0], start[1], months)
    computed = f"{cy:04d}-{cm:02d}"

    if not ocr:
        return computed, "low_confidence"

    diff = abs((ocr[0] * 12 + ocr[1]) - (cy * 12 + cm))
    if diff <= 1:
        return ocr_end_raw, "extracted"

    logger.debug(
        "reconcile_end_date: OCR end %s disagrees with start+duration (%s); using computed",
        ocr_end_raw, computed,
    )
    return computed, "low_confidence"


def _cell_y_center(cell: dict) -> float | None:
    """Vertical center from a Docling cell bbox, for geometric row grouping."""
    bbox = cell.get("bbox")
    if isinstance(bbox, dict):
        if "t" in bbox and "b" in bbox:
            return (float(bbox["t"]) + float(bbox["b"])) / 2.0
        if "y0" in bbox and "y1" in bbox:
            return (float(bbox["y0"]) + float(bbox["y1"])) / 2.0
    prov = cell.get("prov") or []
    if prov and isinstance(prov[0], dict):
        pb = prov[0].get("bbox") or {}
        if "t" in pb and "b" in pb:
            return (float(pb["t"]) + float(pb["b"])) / 2.0
        if "y0" in pb and "y1" in pb:
            return (float(pb["y0"]) + float(pb["y1"])) / 2.0
    return None


def _grid_from_cells_geometric(cells: list[dict], y_tol: float = 8.0) -> dict[int, dict[int, str]]:
    """Cluster cells into logical rows by bbox y-center (robust to offset drift).

    Falls back to offset-index grid when no bbox data is present (safe default)."""
    has_bbox = any(_cell_y_center(c) is not None for c in cells if isinstance(c, dict))
    if not has_bbox:
        logger.debug("No bbox in cells — falling back to offset-index grid")
        return _grid_from_cells(cells)

    valid = [
        (c, _cell_y_center(c))
        for c in cells
        if isinstance(c, dict) and (c.get("text") or "").strip() and _cell_y_center(c) is not None
    ]
    valid.sort(key=lambda x: x[1])

    rows: list[tuple[float, list[dict]]] = []
    for cell, y in valid:
        placed = False
        for i, (ry, members) in enumerate(rows):
            if abs(y - ry) <= y_tol:
                new_avg = (ry * len(members) + y) / (len(members) + 1)
                members.append(cell)
                rows[i] = (new_avg, members)
                placed = True
                break
        if not placed:
            rows.append((y, [cell]))

    grid: dict[int, dict[int, str]] = {}
    for r_idx, (_, members) in enumerate(rows):
        for cell in members:
            text = (cell.get("text") or "").strip()
            if not text:
                continue
            col = int(cell.get("start_col_offset_idx", cell.get("col", 0)) or 0)
            if col in grid.get(r_idx, {}) and len(grid[r_idx][col]) >= len(text):
                continue
            grid.setdefault(r_idx, {})[col] = text
    return grid


def _grid_from_cells(cells: list[dict]) -> dict[int, dict[int, str]]:
    grid: dict[int, dict[int, str]] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        text = (cell.get("text") or "").strip()
        if not text:
            continue
        row = int(cell.get("start_row_offset_idx", cell.get("row", 0)) or 0)
        col = int(cell.get("start_col_offset_idx", cell.get("col", 0)) or 0)
        if col in grid.get(row, {}) and len(grid[row][col]) >= len(text):
            continue
        grid.setdefault(row, {})[col] = text
    return grid


def _identify_columns(grid: dict[int, dict[int, str]]) -> dict[str, int | None]:
    cols: dict[str, int | None] = {"code": 0, "description": 1, "start": None, "end": None}
    for row_idx in sorted(grid)[:2]:
        for col_idx, text in grid[row_idx].items():
            low = text.lower()
            if "coverage" in low or low == "code":
                cols["code"] = col_idx
            elif "description" in low:
                cols["description"] = col_idx
            elif low.startswith("start"):
                cols["start"] = col_idx
            elif low.startswith("end"):
                cols["end"] = col_idx
    if cols["start"] is None or cols["end"] is None:
        all_cols = sorted({col for row in grid.values() for col in row})
        if len(all_cols) >= 4:
            if cols["start"] is None:
                cols["start"] = all_cols[-2]
            if cols["end"] is None:
                cols["end"] = all_cols[-1]
    return cols


def parse_coverage_codes_from_tables(tables: list[dict]) -> list[dict]:
    """Parse Docling table cell grids into coverage-code field-wrapper entries."""
    out: list[dict] = []
    for tbl in tables or []:
        if not isinstance(tbl, dict):
            continue
        page = _page_no(tbl) or 1
        data = tbl.get("data") or {}
        cells = (data.get("table_cells") or []) if isinstance(data, dict) else []
        if not cells:
            continue
        grid = _grid_from_cells_geometric(cells)
        if not grid:
            continue
        cols = _identify_columns(grid)
        code_col = cols["code"]
        desc_col = cols["description"]
        start_col = cols["start"]
        end_col = cols["end"]

        last_entry: dict | None = None
        for row_idx in sorted(grid):
            row = grid[row_idx]
            code_raw = (row.get(code_col) or "").strip()
            desc_raw = (row.get(desc_col) or "").strip()

            codes = _extract_codes(code_raw, desc_raw)
            if codes:
                start_raw = (row.get(start_col) or "").strip() if start_col is not None else ""
                end_raw = (row.get(end_col) or "").strip() if end_col is not None else ""
                for code in codes:
                    entry = _make_entry(code, desc_raw, start_raw, end_raw, page=page)
                    out.append(entry)
                    last_entry = entry
            elif not code_raw and desc_raw and last_entry is not None:
                prev = last_entry["description"]
                prev_val = (prev.get("value") or "") if isinstance(prev, dict) else ""
                merged = f"{prev_val} {desc_raw}".strip()
                last_entry["description"] = _fw(merged, page=page)
                duration, distance = _parse_duration_distance(merged)
                if duration:
                    last_entry["duration"] = _fw(duration, page=page)
                if distance:
                    last_entry["distance"] = _fw(distance, page=page)

    logger.info(
        "coverage_table_parser: parsed %d coverage codes from %d tables",
        len(out),
        len(tables or []),
    )
    return out


def parse_coverage_codes_from_pipe_text(tables_text: str) -> list[dict]:
    """Fallback parser for pipe-delimited table rows."""
    out: list[dict] = []
    last_entry: dict | None = None
    for line in (tables_text or "").splitlines():
        if line.startswith("==="):
            continue
        parts = [part.strip() for part in line.split("|")]
        if not parts:
            continue
        code_raw = parts[0]
        desc = parts[1] if len(parts) > 1 else ""
        start_raw = parts[-2] if len(parts) >= 4 else ""
        end_raw = parts[-1] if len(parts) >= 4 else ""
        codes = _extract_codes(code_raw, desc, line)
        if codes:
            for code in codes:
                entry = _make_entry(code, desc or line, start_raw, end_raw)
                out.append(entry)
                last_entry = entry
        elif last_entry is not None and len(parts) >= 2 and parts[1]:
            prev = last_entry["description"]
            prev_val = (prev.get("value") or "") if isinstance(prev, dict) else ""
            last_entry["description"] = _fw(f"{prev_val} {parts[1]}".strip())
    return out


def merge_into_master(master: dict, parsed_codes: list[dict]) -> dict:
    """Replace sparse LLM coverage codes when deterministic parse found more rows."""
    if not parsed_codes:
        return master
    profiles = master.setdefault("profiles", {})
    table = profiles.setdefault("coverage_code_table", {})
    existing = table.get("coverage_codes") or []
    if len(parsed_codes) >= len(existing):
        table["coverage_codes"] = parsed_codes
        logger.info(
            "coverage_table_parser: replaced %d LLM codes with %d deterministic codes",
            len(existing),
            len(parsed_codes),
        )
    return master
