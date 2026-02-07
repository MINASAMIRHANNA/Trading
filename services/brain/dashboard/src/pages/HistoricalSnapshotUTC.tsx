import { useEffect, useMemo, useState } from "react";
import { runHistoricalSnapshotAtUtc } from "../api/inspector";
import type { UnifiedRole } from "../api/unified";
import { DataTable, KpiCard, Panel, SectionHeader, StatusBadge, formatNum } from "../components/mina";

function localDateTimeToUtcIso(value: string): string | null {
  const txt = String(value || "").trim();
  if (!txt) return null;
  const dt = new Date(txt);
  if (!Number.isFinite(dt.getTime())) return null;
  return dt.toISOString();
}

function toLocalDisplay(value: string): string {
  const dt = new Date(value);
  if (!Number.isFinite(dt.getTime())) return value || "—";
  return dt.toLocaleString();
}

export default function HistoricalSnapshotUTC(props: { initialRole?: UnifiedRole; lockRole?: boolean }) {
  const [role, setRole] = useState<UnifiedRole>(props.initialRole || "paper");
  const [symbol, setSymbol] = useState("SOLUSDT");
  const [market, setMarket] = useState<"futures" | "spot">("futures");
  const [interval, setInterval] = useState<"1m" | "5m" | "15m" | "1h" | "4h" | "1d">("5m");
  const [atLocal, setAtLocal] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [snapshot, setSnapshot] = useState<any>(null);

  useEffect(() => {
    if (props.initialRole) setRole(props.initialRole);
  }, [props.initialRole]);

  useEffect(() => {
    if (!atLocal) {
      const now = new Date();
      now.setMinutes(now.getMinutes() - 15);
      const yyyy = now.getFullYear();
      const mm = String(now.getMonth() + 1).padStart(2, "0");
      const dd = String(now.getDate()).padStart(2, "0");
      const hh = String(now.getHours()).padStart(2, "0");
      const mi = String(now.getMinutes()).padStart(2, "0");
      setAtLocal(`${yyyy}-${mm}-${dd}T${hh}:${mi}`);
    }
  }, [atLocal]);

  const runSnapshot = async () => {
    const s = symbol.trim().toUpperCase();
    const atUtc = localDateTimeToUtcIso(atLocal);
    if (!s) {
      setMessage("Symbol is required.");
      return;
    }
    if (!atUtc) {
      setMessage("Local datetime is required.");
      return;
    }
    const localReadable = toLocalDisplay(atLocal);
    const traceId = `trace-${Date.now()}`;
    setBusy(true);
    setMessage("");
    try {
      const out = await runHistoricalSnapshotAtUtc({
        role,
        symbol: s,
        market,
        interval,
        at_local: localReadable,
        at_utc: atUtc,
        trace_id: traceId,
      });
      setSnapshot(out || null);
      setMessage("");
    } catch (err: any) {
      setMessage(err?.message || "Snapshot run failed.");
    } finally {
      setBusy(false);
    }
  };

  const indicatorRows = useMemo(() => {
    const i = snapshot?.indicators || {};
    return [
      { name: "RSI", value: i?.rsi },
      { name: "ADX", value: i?.adx },
      { name: "ATR", value: i?.atr },
      { name: "ATR %", value: i?.atr_pct },
    ];
  }, [snapshot]);

  const rawJson = useMemo(() => JSON.stringify(snapshot?.raw_indicators || {}, null, 2), [snapshot]);

  const copyRaw = async () => {
    try {
      await navigator.clipboard.writeText(rawJson);
      setMessage("Raw indicators JSON copied.");
    } catch {
      setMessage("Copy failed.");
    }
  };

  return (
    <div>
      <SectionHeader
        title="Historical Snapshot (UTC)"
        subtitle="Pick local datetime, send UTC to Gateway, and inspect candle/indicators/regime/pump score."
        right={message ? <span className="muted">{message}</span> : null}
      />

      <Panel title="Snapshot Inputs">
        <div className="filters-row">
          {!props.lockRole ? (
            <select data-testid="snapshot-role" className="dark-select" value={role} onChange={(e) => setRole(e.target.value as UnifiedRole)}>
              <option value="paper">paper</option>
              <option value="live">live</option>
              <option value="pump">pump</option>
            </select>
          ) : (
            <StatusBadge text={`role=${role}`} tone="info" />
          )}
          <input data-testid="snapshot-symbol" className="dark-input" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="SOLUSDT" />
          <select data-testid="snapshot-market" className="dark-select" value={market} onChange={(e) => setMarket(e.target.value as "futures" | "spot")}>
            <option value="futures">Futures</option>
            <option value="spot">Spot</option>
          </select>
          <input
            data-testid="snapshot-at-local"
            className="dark-input"
            type="datetime-local"
            value={atLocal}
            onChange={(e) => setAtLocal(e.target.value)}
          />
          <select data-testid="snapshot-interval" className="dark-select" value={interval} onChange={(e) => setInterval(e.target.value as any)}>
            <option value="1m">1m</option>
            <option value="5m">5m</option>
            <option value="15m">15m</option>
            <option value="1h">1h</option>
            <option value="4h">4h</option>
            <option value="1d">1d</option>
          </select>
          <button data-testid="snapshot-run" className="action-btn primary" disabled={busy} onClick={() => void runSnapshot()}>
            Run Snapshot
          </button>
        </div>
        <div className="muted" style={{ marginTop: 8 }}>
          Local datetime is converted to UTC ISO before request.
        </div>
      </Panel>

      <Panel title="Summary">
        <div className="kpi-grid">
          <KpiCard label="trace_id" value={snapshot?.trace_id || "—"} />
          <KpiCard label="symbol" value={snapshot?.symbol || "—"} />
          <KpiCard label="regime" value={snapshot?.regime_label || "—"} />
          <KpiCard label="pump score" value={snapshot?.pump?.score ?? "—"} tone={Number(snapshot?.pump?.score || 0) >= 60 ? "warn" : "neutral"} />
          <KpiCard label="candle close" value={formatNum(snapshot?.candle?.close)} />
          <KpiCard label="at_utc" value={snapshot?.at_utc || "—"} />
        </div>
      </Panel>

      <div className="grid-2">
        <Panel title="Candle">
          <DataTable
            rows={snapshot?.candle ? [snapshot.candle] : []}
            emptyText="No candle data yet."
            columns={[
              { key: "open_time_utc", title: "Open Time UTC", render: (row: any) => row.open_time_utc || "—" },
              { key: "close_time_utc", title: "Close Time UTC", render: (row: any) => row.close_time_utc || "—" },
              { key: "open", title: "Open", render: (row: any) => formatNum(row.open, 8) },
              { key: "high", title: "High", render: (row: any) => formatNum(row.high, 8) },
              { key: "low", title: "Low", render: (row: any) => formatNum(row.low, 8) },
              { key: "close", title: "Close", render: (row: any) => formatNum(row.close, 8) },
              { key: "volume", title: "Volume", render: (row: any) => formatNum(row.volume, 4) },
            ]}
          />
        </Panel>

        <Panel title="Indicators">
          <DataTable
            rows={indicatorRows}
            emptyText="No indicators yet."
            columns={[
              { key: "name", title: "Indicator", render: (row: any) => row.name },
              { key: "value", title: "Value", render: (row: any) => (row.value == null ? "—" : formatNum(row.value, 8)) },
            ]}
          />
        </Panel>
      </div>

      <Panel
        title="Raw Indicators JSON"
        right={
          <button data-testid="snapshot-copy-json" className="action-btn" onClick={() => void copyRaw()}>
            Copy JSON
          </button>
        }
      >
        <pre className="code-block">{rawJson || "{}"}</pre>
      </Panel>
    </div>
  );
}
