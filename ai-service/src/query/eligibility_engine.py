"""Session-scoped eligibility slot filling."""

from __future__ import annotations

from datetime import date, datetime

try:
    from dateutil.relativedelta import relativedelta  # type: ignore
except ImportError:
    # Fallback: approximate months as 30 days each
    class relativedelta:  # type: ignore[no-redef]
        def __init__(self, months: int = 0):
            self._days = months * 30
        def __radd__(self, other: datetime) -> datetime:
            from datetime import timedelta
            return other + timedelta(days=self._days)


def fields_needed_for_row(row: dict) -> list[str]:
    period = row.get("coverage_period") or {}
    needed: list[str] = []
    if period.get("duration_months") is not None:
        needed.append("purchase_date")
    if period.get("mileage_limit") is not None:
        needed.append("current_mileage")
    return needed


def missing_eligibility_fields(row: dict, eligibility: dict | None) -> list[str]:
    eligibility = eligibility or {}
    period = row.get("coverage_period") or {}
    missing: list[str] = []
    if period.get("duration_months") is not None and not eligibility.get("purchase_date"):
        missing.append("purchase_date")
    if period.get("mileage_limit") is not None and not eligibility.get("current_mileage"):
        missing.append("current_mileage")
    return missing


def build_eligibility_prompt(missing: list[str], row: dict) -> str:
    cid = row.get("coverage_id") or "coverage"
    name = row.get("coverage_name") or cid
    parts = [f"To evaluate {name} ({cid}), I need:"]
    if "purchase_date" in missing:
        parts.append("in-service or purchase date")
    if "current_mileage" in missing:
        parts.append("current odometer reading")
    return " ".join(parts)


def parse_purchase_date(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def months_since_purchase(purchase_date: str) -> int | None:
    dt = parse_purchase_date(purchase_date)
    if not dt:
        return None
    delta = datetime.utcnow() - dt
    return int(delta.days / 30.44)


# ---------------------------------------------------------------------------
#  §5  Asset eligibility computation (contract-format output)
# ---------------------------------------------------------------------------

def _eq_or_unknown(doc_val: str | None, asset_val: str | None) -> bool:
    """True if doc doesn't restrict, or values match case-insensitively."""
    if not doc_val:
        return True
    if not asset_val:
        return True  # can't contradict → assume match for demo
    return str(doc_val).strip().lower() == str(asset_val).strip().lower()


def _in_or_unknown(doc_list: list | None, asset_val: str | None) -> bool:
    """True if doc doesn't restrict models, or asset model is in the list."""
    if not doc_list:
        return True
    if not asset_val:
        return True
    normalized = [str(m).strip().lower() for m in doc_list]
    return str(asset_val).strip().lower() in normalized


def _year_ok(years_spec: dict | None, asset_year: int | str | None) -> bool:
    """True if no year restriction, or asset year falls within range/list."""
    if not years_spec:
        return True
    if asset_year is None:
        return True
    try:
        yr = int(asset_year)
    except (TypeError, ValueError):
        return True
    # years_spec may be {"from": 2018, "to": 2023} or {"list": [2019, 2020, 2021]}
    if "from" in years_spec and "to" in years_spec:
        return int(years_spec["from"]) <= yr <= int(years_spec["to"])
    if "list" in years_spec:
        return yr in [int(y) for y in years_spec["list"]]
    return True


def _to_int(val) -> int | None:
    if val is None:
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def compute_asset_eligibility(
    row_or_rows: dict | list[dict],
    asset: dict,
    eligibility: dict | None = None,
) -> dict:
    """Compute the full asset_eligibility block per §5 of the contract.

    Returns make_match, model_match, model_year_match, mileage_eligible,
    time_eligible, warranty_expiration_date, etc.
    """
    eligibility = eligibility or {}
    row = row_or_rows[0] if isinstance(row_or_rows, list) else row_or_rows
    p = row.get("coverage_period") or {}
    appl = asset.get("_applicability") or {}

    # Match booleans
    make_match = _eq_or_unknown(appl.get("make"), asset.get("make"))
    model_match = _in_or_unknown(appl.get("models"), asset.get("model"))
    years = appl.get("model_years") or {}
    model_year_match = _year_ok(years, asset.get("model_year"))

    # Time eligibility
    dm = p.get("duration_months")
    pd = eligibility.get("purchase_date")
    exp: str | None = None
    time_eligible: bool | None = None
    if dm is not None and pd:
        start = parse_purchase_date(str(pd))
        if start:
            exp_dt = start + relativedelta(months=int(dm))
            exp = (exp_dt.date() if hasattr(exp_dt, 'date') else exp_dt).isoformat()
            time_eligible = date.today() <= date.fromisoformat(exp)

    # Mileage eligibility
    ml = p.get("mileage_limit")
    cm = eligibility.get("current_mileage")
    mileage_eligible: bool | None = None
    if ml is not None and cm is not None:
        cm_int = _to_int(cm)
        if cm_int is not None:
            mileage_eligible = cm_int <= int(ml)

    return {
        "make_match": make_match,
        "model_match": model_match,
        "model_year_match": model_year_match,
        "mileage_eligible": mileage_eligible,
        "time_eligible": time_eligible,
        "current_mileage": _to_int(cm) if cm is not None else None,
        "warranty_mileage_limit": int(ml) if ml is not None else None,
        "purchase_date": pd,
        "warranty_expiration_date": exp,
    }


def has_limits(row_or_rows: dict | list[dict]) -> bool:
    """True if the coverage row(s) define any time or mileage limit."""
    rows = row_or_rows if isinstance(row_or_rows, list) else [row_or_rows]
    for row in rows:
        p = row.get("coverage_period") or {}
        if p.get("duration_months") is not None or p.get("mileage_limit") is not None:
            return True
    return False

