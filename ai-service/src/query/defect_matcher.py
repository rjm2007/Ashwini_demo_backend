"""Match defect hierarchy targets to ingested coverage_components rows."""

from __future__ import annotations

from difflib import SequenceMatcher

_HIER_WEIGHTS = {"system": 0.45, "subsystem": 0.35, "component_group": 0.20}
_NAME_TIEBREAK = 0.15
_MIN_RAW_SCORE = 0.55  # system-only (0.45) fails; system+subsystem (0.80) or system+group (0.65) passes
_MAX_CANDIDATES = 3


def _norm(value: str | None) -> str:
    return str(value or "").strip().lower()


def _hier(row: dict) -> dict[str, str]:
    h = row.get("coverage_hierarchy") or {}
    return {k: _norm(h.get(k) or row.get(k)) for k in ("system", "subsystem", "component_group")}


def _raw_score(row: dict, target: dict) -> float:
    rh = _hier(row)
    th = {k: _norm(target.get(k)) for k in ("system", "subsystem", "component_group")}
    s = 0.0
    for level, weight in _HIER_WEIGHTS.items():
        tv, rv = th[level], rh[level]
        if not tv or not rv:
            continue
        if tv == rv:
            s += weight
        elif tv in rv or rv in tv:
            s += weight * 0.6
    s += _NAME_TIEBREAK * SequenceMatcher(
        None, _norm(row.get("coverage_name")), _norm(target.get("component_group"))
    ).ratio()
    return s


def match_coverage_rows(
    coverage_rows: list[dict],
    candidate_targets: list[dict],
    *,
    top_n: int = _MAX_CANDIDATES,
    threshold: float = _MIN_RAW_SCORE,
) -> list[dict]:
    if not coverage_rows or not candidate_targets:
        return []
    scored: list[tuple[float, float, dict]] = []
    for row in coverage_rows:
        if not isinstance(row, dict):
            continue
        best_raw, best_conf = 0.0, 1.0
        for t in candidate_targets:
            raw = _raw_score(row, t)
            if raw > best_raw:
                best_raw, best_conf = raw, float(t.get("confidence", 1.0) or 1.0)
        if best_raw >= threshold:  # gate on RAW score (robust to low classifier confidence)
            scored.append((best_raw * best_conf, best_raw, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    seen: set[str] = set()
    out: list[dict] = []
    for _rank, raw, row in scored:
        cid = str(row.get("coverage_id"))
        if cid in seen:
            continue
        seen.add(cid)
        item = dict(row)
        item["_match_score"] = round(raw, 3)
        out.append(item)
        if len(out) >= top_n:
            break
    return out
