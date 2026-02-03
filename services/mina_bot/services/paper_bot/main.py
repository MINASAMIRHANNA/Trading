import os
import sys
import runpy
from pathlib import Path

# ---- Service wrapper (Docker) ----
# Avoid `from main import main` here (circular import), execute project-root main.py.

ROOT = Path(__file__).resolve().parents[2]  # /app (mounted project root)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure relative paths behave the same as running from /app
os.chdir(str(ROOT))

os.environ.setdefault('BOT_ROLE', 'paper')
os.environ.setdefault('BOT_ID', 'paper-1')
os.environ.setdefault('BOT_VERSION', '1.0.0')

if __name__ == '__main__':
    runpy.run_path(str(ROOT / 'main.py'), run_name='__main__')
