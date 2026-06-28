from datetime import date
from dateutil.relativedelta import relativedelta

def _to_int(v):
    try:
        return int(str(v).replace(",", "").strip())
    except Exception:
        return None

def _parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return date.fromisoformat(s) if fmt == "%Y-%m-%d" else __import__("datetime").datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None

def compute_clause_eligibility(row, asset):
    """Eligibility for ONE coverage clause. Each clause has its own limits."""
    p = row.get("coverage_period") or {}
    appl = (asset or {}).get("_applicability") or {}
    dm = p.get("duration_months")
    ml = p.get("mileage_limit")
    pd = (asset or {}).get("purchase_date")
    cm = (asset or {}).get("current_mileage")

    # make/model/year match: true when the warranty does not restrict that field
    def _eq_or_unknown(a, b):
        if not a:
            return True
        return str(a).strip().lower() == str(b or "").strip().lower()
    def _in_or_unknown(lst, b):
        if not lst:
            return True
        return any(str(x).strip().lower() == str(b or "").strip().lower() for x in lst)
    years = appl.get("model_years") or {}
    def _year_ok(y):
        yy = _to_int((asset or {}).get("model_year"))
        if not years or yy is None:
            return True
        if years.get("from") and yy < _to_int(years["from"]):
            return False
        if years.get("to") and yy > _to_int(years["to"]):
            return False
        sp = years.get("specific_years") or []
        if sp:
            return yy in [_to_int(x) for x in sp]
        return True

    exp = None
    time_eligible = None
    sd = _parse_date(pd)
    if dm is not None and sd is not None:
        exp = (sd + relativedelta(months=int(dm))).isoformat()
        time_eligible = date.today() <= date.fromisoformat(exp)

    mileage_eligible = None
    cmi = _to_int(cm)
    if ml is not None and cmi is not None:
        mileage_eligible = cmi <= int(ml)

    return {
        "make_match": _eq_or_unknown(appl.get("make"), (asset or {}).get("make")),
        "model_match": _in_or_unknown(appl.get("models"), (asset or {}).get("model")),
        "model_year_match": _year_ok(None),
        "time_eligible": time_eligible,
        "mileage_eligible": mileage_eligible,
        "current_mileage": cmi,
        "warranty_mileage_limit": ml,
        "duration_months": dm,
        "purchase_date": pd,
        "warranty_expiration_date": exp,
    }

# How far past a limit still counts as "borderline, let a human decide" rather than a clean
# denial. Tune these if your actual policy is stricter/looser than this default.
MILEAGE_OVERAGE_GRACE_RATIO = 1.10   # up to 10% over the mileage limit = borderline
TIME_OVERAGE_GRACE_DAYS = 60         # up to ~2 months past expiration = borderline


def _mileage_overage_state(elig: dict) -> str | None:
    """'ok' | 'close' | 'far' | None (None = no mileage data to judge at all)."""
    me = elig.get("mileage_eligible")
    if me is None:
        return None
    if me:
        return "ok"
    limit = elig.get("warranty_mileage_limit")
    current = elig.get("current_mileage")
    if not limit or current is None:
        return "close"  # failed but no numbers to size the gap — stay conservative
    ratio = current / limit
    return "close" if ratio <= MILEAGE_OVERAGE_GRACE_RATIO else "far"


def _time_overage_state(elig: dict) -> str | None:
    """'ok' | 'close' | 'far' | None (None = no date data to judge at all)."""
    te = elig.get("time_eligible")
    if te is None:
        return None
    if te:
        return "ok"
    exp = elig.get("warranty_expiration_date")
    if not exp:
        return "close"
    try:
        exp_date = date.fromisoformat(exp)
    except Exception:
        return "close"
    days_over = (date.today() - exp_date).days
    return "close" if days_over <= TIME_OVERAGE_GRACE_DAYS else "far"


def decide_one_clause(elig, context_confidence, strong_exclusion):
    """Decision for ONE clause. Strong exclusion overrides eligibility (client Example 2).

    Eligibility has three tiers per factor (time, mileage): within limits, borderline (a little
    over — ambiguous enough that a human should confirm), or clearly over (resolves straight to
    NOT_COVERED, nothing to review). A truck a few hundred miles or a few weeks past a limit is
    genuinely uncertain; a truck millions of miles or years past it is not, and should not get
    the same "needs review" answer as the borderline case.
    """
    if strong_exclusion:
        return "NOT_COVERED"
    if context_confidence < 0.5:
        return "NOT_COVERED"

    mileage_state = _mileage_overage_state(elig)
    time_state = _time_overage_state(elig)
    states = [s for s in (mileage_state, time_state) if s is not None]

    if not states:
        return "POSSIBLY_COVERED"      # matched but no date/mileage to confirm at all
    if "far" in states:
        return "NOT_COVERED"           # clearly, unambiguously outside a hard limit
    if all(s == "ok" for s in states):
        return "COVERED"               # within every limit we could check
    return "POSSIBLY_COVERED"          # borderline on at least one factor — let a human confirm
