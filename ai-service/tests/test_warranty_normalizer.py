"""Unit tests for warranty_normalizer (test.md §A.5)."""

from __future__ import annotations

from src.services.warranty_normalizer import normalize_duration_period


def _period(text: str) -> dict:
    return normalize_duration_period({"duration_text": text})


def test_twelve_months_hundred_thousand_miles():
    p = _period("12 Months/100,000 miles")
    assert p["duration_months"] == 12
    assert p["mileage_limit"] == 100000
    assert p["mileage_unit"] == "miles"


def test_forty_eight_months_six_hundred_k():
    p = _period("48 months / 600K miles")
    assert p["duration_months"] == 48
    assert p["mileage_limit"] == 600000
    assert p["mileage_unit"] == "miles"


def test_sixty_mo_prefers_miles_over_km():
    p = _period("60 mo/500K mi/804672 KM")
    assert p["duration_months"] == 60
    assert p["mileage_limit"] == 500000
    assert p["mileage_unit"] == "miles"


def test_unlimited_miles():
    p = _period("12 months / Unlimited miles")
    assert p["duration_months"] == 12
    assert p["mileage_unit"] == "unlimited"
    assert p["mileage_limit"] is None


def test_ocr_zero_miles_discarded():
    p = _period("60 Months/000 Miles")
    assert p["duration_months"] == 60
    assert p["mileage_limit"] is None


def test_year_and_mileage_range():
    p = _period("2 to 7 Years / 100,000 to 500,000 miles")
    assert p["duration_months"] == 84
    assert p["range"]["duration_months_from"] == 24
    assert p["range"]["duration_months_to"] == 84
    assert p["mileage_limit"] == 500000
    assert p["range"]["mileage_from"] == 100000
    assert p["range"]["mileage_to"] == 500000


def test_hours_and_mileage():
    p = _period("24 months or 250,000 miles or 6,250 hours")
    assert p["duration_months"] == 24
    assert p["mileage_limit"] == 250000
    assert p["hours_limit"] == 6250


def test_never_emits_zero_mileage():
    p = normalize_duration_period({"duration_text": "60 months", "mileage_limit": 0})
    assert p["mileage_limit"] is None
