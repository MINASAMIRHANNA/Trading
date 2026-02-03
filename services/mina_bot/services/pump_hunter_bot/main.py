import os
import sys
import runpy
from pathlib import Path

# ---- Service wrapper (Docker) ----
# Ensure /app is on sys.path, then execute project-root pump_hunter.py.
# (Importing pump_hunter directly sometimes fails depending on sys.path ordering.)

ROOT = Path(__file__).resolve().parents[2]  # /app (mounted project root)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure relative paths behave the same as running from /app
os.chdir(str(ROOT))

os.environ.setdefault('BOT_ROLE', 'pump')
os.environ.setdefault('BOT_ID', 'pump-1')
os.environ.setdefault('BOT_VERSION', '1.0.0')

if __name__ == '__main__':
    runpy.run_path(str(ROOT / 'pump_hunter.py'), run_name='__main__')
