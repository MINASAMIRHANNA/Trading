import os
import sys
import runpy
from pathlib import Path

# ---- Service wrapper (Docker) ----
# This file is intentionally named main.py, but we must NOT do `from main import main`
# because it causes a circular import (it imports itself). Instead, we execute the
# project-root /app/main.py as __main__.

ROOT = Path(__file__).resolve().parents[2]  # /app (mounted project root)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure relative paths behave the same as running from /app
os.chdir(str(ROOT))

os.environ.setdefault('BOT_ROLE', 'live')
os.environ.setdefault('BOT_ID', 'live-1')
os.environ.setdefault('BOT_VERSION', '1.0.0')

if __name__ == '__main__':
    runpy.run_path(str(ROOT / 'main.py'), run_name='__main__')
