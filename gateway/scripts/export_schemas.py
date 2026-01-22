import json
from pathlib import Path

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
