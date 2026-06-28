"""Verify invoice_table_parser extracts line items and totals."""

from src.services.invoice_table_parser import parse_invoice_from_tables


def cell(text, r, c):
    return {"text": text, "start_row_offset_idx": r, "start_col_offset_idx": c}


def v(fw):
    return fw.get("value") if isinstance(fw, dict) else fw


tables = [{
    "prov": [{"page_no": 1}],
    "data": {"table_cells": [
        cell("Supp.", 0, 0), cell("Part", 0, 1), cell("Description / Ref Number", 0, 2),
        cell("U/M", 0, 3), cell("Quantity", 0, 4), cell("Price", 0, 5), cell("Extended Price", 0, 6),
        cell("1076684", 1, 1), cell("ATF KENDALL/DEXMERC", 1, 2), cell("Each", 1, 3), cell("2.0", 1, 4), cell("$3.99", 1, 5), cell("$7.98", 1, 6),
        cell("85020581", 2, 1), cell("TRANSMISSION", 2, 2), cell("Each", 2, 3), cell("1.0", 2, 4), cell("$14,242.33", 2, 5), cell("$14,242.33", 2, 6),
        cell("Total Parts:", 10, 2), cell("$15,163.17", 10, 6),
        cell("Total Labor:", 11, 2), cell("$1,409.30", 11, 6),
        cell("Grand Total", 12, 2), cell("$18,854.65", 12, 6),
    ]},
}]


def test_line_items_extracted():
    result = parse_invoice_from_tables(tables)
    items = result["line_items"]
    assert len(items) >= 2
    descs = [v(i["description"]) for i in items if v(i["description"])]
    assert any("TRANSMISSION" in d for d in descs)


def test_grand_total_extracted():
    result = parse_invoice_from_tables(tables)
    totals = result["totals"]
    assert totals.get("grand_total")
    assert "18854" in str(v(totals["grand_total"])).replace(",", "")
