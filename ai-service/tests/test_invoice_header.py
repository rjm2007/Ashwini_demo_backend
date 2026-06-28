"""Verify invoice_header_parser against real OCR text of the 1038 invoice page."""

from src.services.invoice_header_parser import (
    looks_like_invoice,
    merge_invoice_header,
    parse_invoice_header,
)

REAL_OCR = """Bill To: Trans 99 Logistics
367 Speedvale Ave W
Customer P/O: chale jinsalaco
Invoice: 01853852
Date / Hour: 3/29/2019 3:47:06PM
Repair Order: 53852
Customer: 7135
Total Invoice: $ 18,854.65
Unit Number: 1038
Model Year: 2016
VIN: 4V4NC9EH9GN929394
In-Service Date: 12/16/2015
Complaint: towed in - customer reports bull gear failure
customer reports bull gear failure - towed in
Make/Model: VOLVO VNL670
Meter: 701502 Kilometers
ECM Reading: 14422
Department: Service
Correction: performed inspection , noise is confirmed but not a bull gear failure, noise is coming from the transmission, inspected transmission and found unit has been towed while drive shafts still in, removed and prep installl transmission assy and lines and hoses, fluid ect. program unit and perform roadtest all ok.
Supp. Part Description / Ref Number
85020581 TRANSMISSION
Total Parts:
Total Core Charge:
$15,163.17
$7,494.55
HST $2,169.12
"""


def v(fw):
    return fw.get("value") if isinstance(fw, dict) else fw


def test_looks_like_invoice():
    assert looks_like_invoice(REAL_OCR)


def test_unit_number():
    result = parse_invoice_header(REAL_OCR)
    assert v(result["unit_number"]) == "1038"


def test_grand_total():
    result = parse_invoice_header(REAL_OCR)
    assert v(result["totals"]["grand_total"]) == "18854.65"


def test_core_charge_not_misbound():
    result = parse_invoice_header(REAL_OCR)
    assert v(result["totals"].get("core_charge")) != "15163.17"


def test_complaint_clean():
    result = parse_invoice_header(REAL_OCR)
    comp = v(result["complaint"]).lower()
    assert "bull gear" in comp
    assert "department" not in comp
    assert "volvo" not in comp


def test_correction_captured():
    result = parse_invoice_header(REAL_OCR)
    assert "transmission" in v(result["correction"]).lower()


def test_customer_bill_to():
    result = parse_invoice_header(REAL_OCR)
    assert v(result["customer"]) == "Trans 99 Logistics"


def test_merge_preserves_line_items():
    result = parse_invoice_header(REAL_OCR)
    profile = {"line_items": [{"description": {"value": "TRANSMISSION", "status": "extracted"}}]}
    merge_invoice_header(profile, dict(result))
    assert v(profile["unit_number"]) == "1038"
    assert v(profile["totals"]["grand_total"]) == "18854.65"
    assert profile["line_items"]
