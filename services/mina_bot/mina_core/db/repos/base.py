from __future__ import annotations

import json
from typing import Any, Dict

def row_to_dict(r: Any) -> Dict[str, Any]:
    """Convert sqlite3.Row / pg_compat.HybridRow / dict into a plain dict safely."""
    if r is None:
        return {}
    if isinstance(r, dict):
        return r
    # sqlite3.Row supports dict(r)
    try:
        return dict(r)
    except Exception:
        pass
    # pg_compat.HybridRow exposes keys() + __getitem__
    if hasattr(r, "keys"):
        try:
            return {k: r[k] for k in r.keys()}
        except Exception:
            pass
    cols = getattr(r, "columns", None)
    vals = getattr(r, "values", None)
    if cols and vals:
        try:
            return dict(zip(list(cols), list(vals)))
        except Exception:
            pass
    return {}

def safe_json_loads(s: Any, default: Any) -> Any:
    try:
        if s is None:
            return default
        if isinstance(s, (dict, list)):
            return s
        s2 = str(s)
        return json.loads(s2) if s2 else default
    except Exception:
        return default
