import { useEffect, useMemo, useState } from "react";
import { fetchMinaAnalytics } from "../api/minaPages";
import type { UnifiedRole } from "../api/unified";
import { DataTable, KpiCard, Panel, SectionHeader, formatNum, toneFromValue } from "../components/mina";

function pickNumber(obj: any, keys: string[]): number | null {
  for (const k of keys) {
    const v = obj?.[k];
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

export default function MinaAnalytics() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [data, setData] = useState<any>(null);
  const [message, setMessage] = useState("");
  const [lastUpdated, setLastUpdated] = useState("");

  const load = async () => {
    try {
      const out = await fetchMinaAnalytics(role);
      setData(out);
      setLastUpdated(new Date().toISOString());
      setMessage("");
    } catch (err: any) {
      setMessage(err?.message || "Failed to load analytics.");
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  const kpis = useMemo(() => {
    const src = data?.summary || data || {};
    const trades = pickNumber(src, ["trades", "total_trades", "n_trades"]);
    const winRate = pickNumber(src, ["win_rate", "wr", "winrate"]);
    const expectancy = pickNumber(src, ["expectancy", "exp"]);
    const avgPnl = pickNumber(src, ["avg_pnl", "avg_pnl_pct", "mean_pnl"]);
    return [
      { label: "Trades", value: trades },
      { label: "Win Rate", value: winRate, suffix: "%" },
      { label: "Expectancy", value: expectancy, tone: toneFromValue(expectancy) },
      { label: "Avg PnL", value: avgPnl, tone: toneFromValue(avgPnl) },
    ];
  }, [data]);

  const sections = useMemo(() => {
    if (!data || typeof data !== "object") return [];
    return Object.entries(data).map(([key, value]) => ({
      key,
      kind: Array.isArray(value) ? "array" : typeof value,
      value,
    }));
  }, [data]);

  return (
    <div>
      <SectionHeader
        title="Analytics"
        subtitle="Equivalent of Mina /analytics page through unified gateway."
        right={lastUpdated ? <span className="muted">Last updated: {lastUpdated}</span> : null}
      />

      <Panel title="Scope">
        <div className="filters-row">
          <select className="dark-select" value={role} onChange={(e) => setRole(e.target.value as UnifiedRole)}>
            <option value="paper">paper</option>
            <option value="live">live</option>
            <option value="pump">pump</option>
          </select>
          <button className="action-btn primary" onClick={() => void load()}>
            Refresh
          </button>
          {message ? <span className="muted">{message}</span> : null}
        </div>
      </Panel>

      <Panel title="Top Metrics">
        <div className="kpi-grid">
          {kpis.map((k) => (
            <KpiCard
              key={k.label}
              label={k.label}
              value={k.value === null ? "—" : `${formatNum(k.value)}${k.suffix || ""}`}
              tone={(k as any).tone || "neutral"}
            />
          ))}
        </div>
      </Panel>

      <Panel title="Analytics Sections">
        <DataTable
          rows={sections}
          emptyText="No analytics data."
          columns={[
            { key: "key", title: "Section", render: (row: any) => row.key },
            { key: "kind", title: "Type", render: (row: any) => row.kind },
            {
              key: "value",
              title: "Value",
              render: (row: any) =>
                row.kind === "object" || row.kind === "array"
                  ? JSON.stringify(row.value)
                  : String(row.value ?? "—"),
            },
          ]}
          enableCopy
        />
      </Panel>
    </div>
  );
}
