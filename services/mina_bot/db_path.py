"""db_path.py

Sprint 2 (stability): DB path pinning.

Problem
- Running the project from different working directories can accidentally create multiple
  bot_data.db files (e.g., one in project root, one in ./dashboard, one in cwd).
- That leads to "dashboard shows empty data" / "bot heartbeat missing" / confusing behavior.

Solution
- Pin a single DB path using a small lock file in the project root.
- On first run, we choose the best existing DB candidate and write it to .db_path.
- Next runs always use the pinned path regardless of current working directory.

Notes
- This keeps behavior backward-compatible: if you already have a DB in a non-root location,
  the first run will detect and pin it.
- You can manually override by editing .db_path (a single line absolute path).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional


PROJECT_ROOT = Path(__file__).resolve().parent
PIN_FILE = PROJECT_ROOT / ".db_path"
DEFAULT_DB_NAME = "bot_data.db"

# ---------------------------------------------------------------------
# v1 Split: role-aware DB pinning
# ---------------------------------------------------------------------
ROLE_ALIASES = {
    'arena': 'paper',
    'paper': 'paper',
    'live': 'live',
    'pump': 'pump',
    'baseline': '',
    '': '',
}

PIN_FILE_MAP = {
    'paper': '.db_path_paper',
    'live': '.db_path_live',
    'pump': '.db_path_pump',
}

DB_NAME_MAP = {
    'paper': 'bot_data_paper.db',
    'live': 'bot_data_live.db',
    'pump': 'bot_data_pump.db',
}


def _normalize_role(role: str | None) -> str:
    r = str(role or '').strip().lower()
    return ROLE_ALIASES.get(r, r)


def _pin_file_for_role(role: str | None) -> Path:
    r = _normalize_role(role)
    name = PIN_FILE_MAP.get(r)
    return PROJECT_ROOT / name if name else PIN_FILE


def _db_name_for_role(role: str | None, db_name: str | None = None) -> str:
    r = _normalize_role(role)
    if r in DB_NAME_MAP:
        return DB_NAME_MAP[r]
    return db_name or DEFAULT_DB_NAME


def _read_pin_file(pin_file: Path) -> Optional[str]:
    try:
        if pin_file.exists():
            s = pin_file.read_text(encoding='utf-8').strip()
            return s or None
    except Exception:
        return None
    return None


def _write_pin_file(pin_file: Path, pth: str) -> None:
    try:
        pin_file.write_text(str(pth).strip() + '\n', encoding='utf-8')
    except Exception:
        pass



def _read_pin() -> Optional[str]:
    try:
        if PIN_FILE.exists():
            s = PIN_FILE.read_text(encoding="utf-8").strip()
            return s or None
    except Exception:
        return None
    return None


def _write_pin(p: str) -> None:
    try:
        PIN_FILE.write_text(str(p).strip() + "\n", encoding="utf-8")
    except Exception:
        pass


def find_db_files(db_name: str = DEFAULT_DB_NAME) -> List[str]:
    """Find existing bot_data.db files in likely locations."""
    candidates = [
        PROJECT_ROOT / db_name,
        PROJECT_ROOT.parent / db_name,
        (PROJECT_ROOT / "dashboard") / db_name,
        Path(os.getcwd()) / db_name,
    ]
    found: List[str] = []
    for p in candidates:
        try:
            if p.exists():
                rp = str(p.resolve())
                if rp not in found:
                    found.append(rp)
        except Exception:
            continue
    return found


def get_db_path(db_name: str = DEFAULT_DB_NAME, role: str | None = None) -> str:
    """Return the pinned DB path, creating/updating the pin file as needed.

    v1 Split: if BOT_ROLE (or role param) is set to live/paper/pump,
    use role-specific pin file + role-specific default db name.
    """
    eff_role = _normalize_role(role or os.getenv('BOT_ROLE') or '')
    pin_file = _pin_file_for_role(eff_role)
    eff_db_name = _db_name_for_role(eff_role, db_name)

    pinned = _read_pin_file(pin_file)
    if pinned:
        try:
            pp = Path(pinned)
            if pp.exists() or pp.parent.exists():
                return str(pp)
        except Exception:
            pass

    root_db = (PROJECT_ROOT / eff_db_name)
    try:
        if root_db.exists():
            _write_pin_file(pin_file, str(root_db.resolve()))
            return str(root_db.resolve())
    except Exception:
        pass

    found = find_db_files(db_name=eff_db_name)
    if found:
        _write_pin_file(pin_file, found[0])
        return found[0]

    _write_pin_file(pin_file, str(root_db.resolve()))
    return str(root_db.resolve())


def describe_db_state(db_name: str = DEFAULT_DB_NAME) -> dict:
    """Small helper for diagnostics/doctor."""
    try:
        eff_role = _normalize_role(os.getenv('BOT_ROLE') or '')
        pin_file = _pin_file_for_role(eff_role)
        eff_db_name = _db_name_for_role(eff_role, db_name)
        pinned = _read_pin_file(pin_file)
        found = find_db_files(db_name=eff_db_name)
        return {
            'role': eff_role,
            'role_pin_file': str(pin_file),
            'role_db_name': str(eff_db_name),
            "project_root": str(PROJECT_ROOT),
            "pin_file": str(PIN_FILE),
            "pinned": pinned or "",
            "found": found,
            "duplicates": [p for p in found if pinned and p != pinned],
        }
    except Exception:
        return {
            "project_root": str(PROJECT_ROOT),
            "pin_file": str(PIN_FILE),
            "pinned": "",
            "found": [],
            "duplicates": [],
        }
