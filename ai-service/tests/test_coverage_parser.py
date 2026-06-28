"""Verify coverage_table_parser against synthetic Docling table layout."""

from src.services.coverage_table_parser import (
    merge_into_master,
    parse_coverage_codes_from_pipe_text,
    parse_coverage_codes_from_tables,
    reconcile_end_date,
)


def cell(text, row, col):
    return {"text": text, "start_row_offset_idx": row, "start_col_offset_idx": col}


def v(fw):
    return fw.get("value") if isinstance(fw, dict) else fw


tables = [{
    "prov": [{"page_no": 1}],
    "data": {"table_cells": [
        cell("Coverage", 0, 0), cell("Description", 0, 1), cell("Start", 0, 2), cell("End", 0, 3),
        cell("D0001", 1, 0), cell("Truck, 12 Months/100,000 miles - VEHICLE WARRANTY CLAIM JOB", 1, 1), cell("2019-03-21", 1, 2), cell("2020-03-21", 1, 3),
        cell("HAC49", 2, 0), cell("HVAC 48 MONTHS - VEH WARRANTY CLAIM JOB (DC28)", 2, 1), cell("2019-03-21", 2, 2), cell("2023-03-21", 2, 3),
        cell("TOW1", 3, 0), cell("Towing on warrantable chassis failures 3 months/5,000 miles - BREAKDOWN CLAIM", 3, 1), cell("2019-03-21", 3, 2), cell("2019-06-21", 3, 3),
        cell("TOW2", 4, 0), cell("TOWING on warrantable engine failures 24 months/250,000 miles", 4, 1), cell("2019-03-21", 4, 2), cell("2021-03-21", 4, 3),
        cell("BREAKDOWN CLAIM JOB (DC10)", 5, 1),
        cell("U06", 6, 0), cell("Standard Engine Warranty: 24 months/250,000 Miles/402,336 KM", 6, 1), cell("2019-03-21", 6, 2), cell("2021-03-21", 6, 3),
        cell("U06A", 7, 0), cell("Major Engine Components EPA17: 60 mo/500K mi/804672 KM", 7, 1), cell("2019-03-21", 7, 2), cell("2024-03-21", 7, 3),
        cell("U030", 8, 0), cell("Frame & Crossmembers, 72 Months/750,000 Miles", 8, 1), cell("2019-03-21", 8, 2), cell("2026-03-21", 8, 3),
        cell("U065", 9, 0), cell("Auto/Manual Transmission (AMT), 60 Months/750,000 Miles", 9, 1), cell("2019-03-21", 9, 2), cell("2024-03-21", 9, 3),
        cell("Z0421", 10, 0), cell("INFO ONLY NO CLAIMS: 24 MONTHS - UPTIME SERVICES BUNDLE", 10, 1), cell("0000-00-00", 10, 2), cell("0000-00-00", 10, 3),
    ]},
}]


def test_parse_all_codes():
    codes = parse_coverage_codes_from_tables(tables)
    by_code = {v(c["code"]): c for c in codes}
    assert len(codes) == 9
    for expected in ["D0001", "HAC49", "TOW1", "TOW2", "U06", "U06A", "U030", "U065", "Z0421"]:
        assert expected in by_code


def test_hac49_description_aligned():
    codes = parse_coverage_codes_from_tables(tables)
    by_code = {v(c["code"]): c for c in codes}
    assert "HVAC" in v(by_code["HAC49"]["description"])
    assert "Towing" not in v(by_code["HAC49"]["description"])


def test_u06_disambiguation():
    codes = parse_coverage_codes_from_tables(tables)
    by_code = {v(c["code"]): c for c in codes}
    assert "Standard Engine" in v(by_code["U06"]["description"])
    assert v(by_code["U06"]["category"]) == "engine"
    assert v(by_code["U065"]["category"]) == "transmission"


def test_u030_end_date_reconciled():
    # OCR cell says 2026-03-21; start 2019-03 + 72 months = 2025-03 → corrected
    codes = parse_coverage_codes_from_tables(tables)
    by_code = {v(c["code"]): c for c in codes}
    assert v(by_code["U030"]["end_date"]) == "2025-03"


def test_correct_dates_unchanged():
    codes = parse_coverage_codes_from_tables(tables)
    by_code = {v(c["code"]): c for c in codes}
    assert v(by_code["U065"]["end_date"]) == "2024-03-21"
    assert v(by_code["U06"]["end_date"]) == "2021-03-21"


def test_reconcile_end_date_standalone():
    val, _ = reconcile_end_date("2019-03-21", "72 months", "2026-03-21")
    assert val == "2025-03"
    val2, _ = reconcile_end_date("2019-03-21", "48 months", "2023-03-21")
    assert val2 == "2023-03-21"
    val3, _ = reconcile_end_date("2019-03-21", "", "2024-03-21")
    assert val3 == "2024-03-21"
    val4, _ = reconcile_end_date("2019-03-21", "72 months", "")
    assert val4 == "2025-03"


def test_wrapped_tow2_description():
    codes = parse_coverage_codes_from_tables(tables)
    by_code = {v(c["code"]): c for c in codes}
    assert "BREAKDOWN CLAIM JOB (DC10)" in v(by_code["TOW2"]["description"])
    assert "DC10" not in v(by_code["TOW1"]["description"])


def test_duration_distance_parsed():
    codes = parse_coverage_codes_from_tables(tables)
    by_code = {v(c["code"]): c for c in codes}
    assert v(by_code["U030"]["duration"]) == "72 months"
    assert "750,000 miles" in v(by_code["U030"]["distance"])


def test_placeholder_date_low_confidence():
    codes = parse_coverage_codes_from_tables(tables)
    by_code = {v(c["code"]): c for c in codes}
    assert by_code["Z0421"]["start_date"]["status"] == "low_confidence"


def test_merge_into_master():
    codes = parse_coverage_codes_from_tables(tables)
    master = {"profiles": {"coverage_code_table": {"coverage_codes": [{"code": {"value": "D0001"}}]}}}
    merge_into_master(master, codes)
    assert len(master["profiles"]["coverage_code_table"]["coverage_codes"]) == 9


def test_pipe_text_fallback():
    pipe = (
        "U06 | Standard Engine Warranty: 24 months/250,000 Miles | 2019-03-21 | 2021-03-21\n"
        "HAC49 | HVAC 48 MONTHS | 2019-03-21 | 2023-03-21"
    )
    parsed = parse_coverage_codes_from_pipe_text(pipe)
    assert len(parsed) == 2
    assert v(parsed[0]["code"]) == "U06"
