import { useMemo, useState } from "react";
import { fetchMinaAudit } from "../api/minaPages";
import type { UnifiedRole } from "../api/unified";
import { DataTable, Panel, SectionHeader } from "../components/mina";

function asRows(data: any): any[] {
  if (!data || typeof data !== "object") return [];
  for (const key of ["items", "trades", "rows", "events", "candles", "signals"]) {
    if (Array.isArray(data[key])) return data[key];
  }
  const firstArray = Object.values(data).find((v) => Array.isArray(v));
  return Array.isArray(firstArray) ? firstArray : [];
}

export default function MinaAudit() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [interval, setInterval] = useState("5m");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [data, setData] = useState<any>(null);
  const [message, setMessage] = useState("");
  const [lastUpdated, setLastUpdated] = useState("");
  const [loading, setLoading] = useState(false);

  const run = async () => {
    if (!symbol.trim()) {
      setMessage("symbol is required");
      return;
    }
    setLoading(true);
    try {
      const out = await fetchMinaAudit(role, {
        symbol: symbol.trim().toUpperCase(),
        interval: interval || "5m",
        start: start || undefined,
        end: end || undefined,
      });
      setData(out);
      setLastUpdated(new Date().toISOString());
      setMessage("");
    } catch (err: any) {
      setMessage(err?.message || "Audit request failed.");
    } finally {
      setLoading(false);
    }
  };

  const rows = useMemo(() => asRows(data), [data]);

  const columns = useMemo(() => {
    const sample = rows[0];
    const keys = sample && typeof sample === "object" ? Object.keys(sample).slice(0, 8) : ["value"];
    return keys.map((k) => ({
      key: k,
      title: k,
      render: (row: any) => {
        const v = row?.[k];
        if (typeof v === "object") return JSON.stringify(v);
        return String(v ?? "—");
      },
    }));
  }, [rows]);

  return (
    <div>
      <SectionHeader
        title="Audit"
        subtitle="Equivalent of Mina /audit with symbol/interval controls."
        right={lastUpdated ? <span className="muted">Last updated: {lastUpdated}</span> : null}
      />

      <Panel title="Audit Controls">
        <div className="filters-row">
          <select className="dark-select" value={role} onChange={(e) => setRole(e.target.value as UnifiedRole)}>
            <option value="paper">paper</option>
            <option value="live">live</option>
            <option value="pump">pump</option>
          </select>
          <input className="dark-input" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="Symbol (e.g. BTCUSDT)" />
          <input className="dark-input" value={interval} onChange={(e) => setInterval(e.target.value)} placeholder="Interval (e.g. 5m)" />
          <input className="dark-input" value={start} onChange={(e) => setStart(e.target.value)} placeholder="Start (optional)" />
          <input className="dark-input" value={end} onChange={(e) => setEnd(e.target.value)} placeholder="End (optional)" />
          <button className="action-btn primary" disabled={loading} onClick={() => void run()}>
            {loading ? "Running..." : "Run Audit"}
          </button>
          {message ? <span className="muted">{message}</span> : null}
        </div>
      </Panel>

      <div className="grid-2">
        <Panel title="Audit Summary">
          <DataTable
            rows={Object.entries((data || {}) as Record<string, unknown>).map(([k, v]) => ({
              key: k,
              value: typeof v === "object" ? JSON.stringify(v) : String(v ?? "—"),
            }))}
            columns={[
              { key: "key", title: "Field", render: (row: any) => row.key },
              { key: "value", title: "Value", render: (row: any) => row.value },
            ]}
            emptyText="No audit result."
          />
        </Panel>
        <Panel title="Audit Rows">
          <DataTable rows={rows} columns={columns} emptyText="No row-level audit data." enableCopy />
        </Panel>
      </div>
    </div>
  );
}
