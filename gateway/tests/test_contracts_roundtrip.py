from shared_contracts.common import BotIdentity, TraceContext
from shared_contracts import SignalEvent, TradeEvent, HealthEvent


def test_signal_roundtrip():
    e = SignalEvent(
        identity=BotIdentity(bot_id='mina', bot_role='brain', bot_version='1.0'),
        trace=TraceContext(decision_id='dec-00001', trace_id='trace-00001'),
        symbol='BTCUSDT',
        side='LONG',
        decision='DO_NOT_TRADE',
        probability_calibrated=0.12,
        veto_passed=False,
        veto_reasons=['spread_too_high'],
        risk_params={'sl_pct': 0.7},
    )
    payload = e.model_dump_json()
    e2 = SignalEvent.model_validate_json(payload)
    assert e2.symbol == 'BTCUSDT'
    assert e2.schema_version == 1


def test_trade_roundtrip():
    e = TradeEvent(
        identity=BotIdentity(bot_id='mina', bot_role='mina_live', bot_version='1.0'),
        trace=TraceContext(decision_id='dec-00001', trace_id='trace-00001'),
        symbol='BTCUSDT',
        action='OPEN',
        price=100.0,
        qty=0.01,
    )
    e2 = TradeEvent.model_validate_json(e.model_dump_json())
    assert e2.action == 'OPEN'


def test_health_roundtrip():
    e = HealthEvent(
        identity=BotIdentity(bot_id='gateway', bot_role='gateway', bot_version='0.1'),
        trace=TraceContext(decision_id='dec-00099', trace_id='trace-00099'),
        service_name='brain_api',
        status='OK',
        ws_connected=True,
        metrics={'latency_ms': 12},
    )
    e2 = HealthEvent.model_validate_json(e.model_dump_json())
    assert e2.service_name == 'brain_api'
