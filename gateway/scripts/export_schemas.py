import json
import sys
from pathlib import Path

# Make this script runnable both ways:
# 1) without installing the package (pure repo checkout)
# 2) after `pip install -e .`
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared_contracts import SignalEvent, TradeEvent, HealthEvent

OUT = Path('schemas')
OUT.mkdir(parents=True, exist_ok=True)

schemas = {
    'SignalEvent.schema.json': SignalEvent.model_json_schema(),
    'TradeEvent.schema.json': TradeEvent.model_json_schema(),
    'HealthEvent.schema.json': HealthEvent.model_json_schema(),
}

for name, schema in schemas.items():
    (OUT / name).write_text(json.dumps(schema, indent=2), encoding='utf-8')

print(f"Exported {len(schemas)} schemas to {OUT.resolve()}")
