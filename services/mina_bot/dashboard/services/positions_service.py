from __future__ import annotations

from typing import Any, Callable, Dict, List


def get_positions(
    db: Any,
    get_real_positions: Callable[[], Dict[str, Any]],
    positions_status_map: Callable[[], Dict[str, Any]],
    normalize_side: Callable[[str], str],
    public_price: Callable[[str, str], float],
) -> List[dict]:
    """Return positions payload for the dashboard.

    This is a thin wrapper around the legacy implementation that already:
    - prefers TradesRepo (repo-first)
    - verifies live positions using execution monitor / exchange
    - backfills unrealized PnL for paper/test using public prices

    Keeping this wrapper lets dashboard/app.py stay slim without changing behavior.
    """
    try:
        from dashboard.legacy_positions import get_positions_data  # type: ignore
        return get_positions_data(db, get_real_positions, positions_status_map, normalize_side, public_price)
    except Exception:
        return []
