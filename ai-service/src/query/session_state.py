"""Session-scoped eligibility cache (B10)."""

from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_TTL = 6 * 3600
_STORE: dict[str, dict] = {}


def get_eligibility(session_id: str | None) -> dict:
    if not session_id:
        return {}
    with _LOCK:
        record = _STORE.get(session_id)
        if not record:
            return {}
        if time.time() - record["ts"] > _TTL:
            _STORE.pop(session_id, None)
            return {}
        return dict(record["eligibility"])


def merge_eligibility(session_id: str | None, values: dict | None) -> dict:
    values = values or {}
    if not session_id:
        return dict(values)
    with _LOCK:
        record = _STORE.get(session_id) or {"eligibility": {}, "ts": time.time()}
        record["eligibility"].update({k: v for k, v in values.items() if v is not None})
        record["ts"] = time.time()
        _STORE[session_id] = record
        return dict(record["eligibility"])


def clear_session(session_id: str | None) -> None:
    if session_id:
        with _LOCK:
            _STORE.pop(session_id, None)
