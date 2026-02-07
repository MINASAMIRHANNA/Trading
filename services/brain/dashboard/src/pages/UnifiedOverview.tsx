import { useEffect, useMemo, useState } from "react";
import { fetchUnifiedOverview, fetchUnifiedSystemHealth, type UnifiedRole } from "../api/unified";
import { DataTable, KpiCard, Panel, SectionHeader, StatusPill, formatNum } from "../components/mina";

export default function UnifiedOverview() {
  const [overview, setOverview] = useState<any>(null);
  const [healthRows, setHealthRows] = useState<any[]>([]);
  const [message, setMessage] = useState("");
  const [lastUpdated, setLastUpdated] = useState("");

  const load = async () => {
    try {
      const ov = await fetchUnifiedOverview();
      const roles: UnifiedRole[] = ["paper", "live", "pump"];
      const health = await Promise.all(
        roles.map(async (role) => ({ role, ...(await fetchUnifiedSystemHealth(role)) })),
      );
      setOverview(ov || {});
      setHealthRows(health || []);
      setLastUpdated(new Date().toISOString());
      setMessage("");
    } catch (err: any) {
      setMessage(err?.message || "Failed to load unified overview.");
    }
  };

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 7000);
    return () => clearInterval(id);
  }, []);

  const roleStats = useMemo(() => {
    const d = overview?.dashboards || {};
    return (["paper", "live", "pump"] as UnifiedRole[]).map((r) => {
      const s = d?.[r]?.stats || {};
      const signals = d?.[r]?.signals_preview || [];
      return {
        role: r,
        trades: s?.trades ?? 0,
        win_rate: s?.win_rate ?? 0,
        pnl: s?.pnl ?? 0,
        signals: Array.isArray(signals) ? signals.length : 0,
      };
    });
  }, [overview]);

  const brain = overview?.brain || {};

  return (
    <div>
      <SectionHeader
        title="Unified Overview"
        subtitle="Gateway-backed snapshot for paper/live/pump and brain analytics."
        right={message ? <span className="muted">{message}</span> : <span className="muted">Last updated: {lastUpdated || "—"}</span>}
      />

      <Panel title="Top Summary Cards">
        <div className="kpi-grid">
          <KpiCard label="Brain Trades" value={formatNum(brain?.trades ?? 0, 0)} />
          <KpiCard label="Brain Win Rate" value={`${formatNum(brain?.win_rate ?? 0)}%`} tone={Number(brain?.win_rate || 0) >= 50 ? "good" : "warn"} />
          <KpiCard label="Brain Expectancy" value={formatNum(brain?.expectancy ?? 0, 6)} tone={Number(brain?.expectancy || 0) >= 0 ? "good" : "bad"} />
          <KpiCard label="Roles" value="paper / live / pump" />
        </div>
      </Panel>

      <div className="grid-2">
        <Panel title="Role Stats">
          <DataTable
            rows={roleStats}
            emptyText="No role stats yet."
            columns={[
              { key: "role", title: "Role", render: (row: any) => row.role },
              { key: "trades", title: "Trades", render: (row: any) => formatNum(row.trades, 0) },
              { key: "win_rate", title: "Win Rate", render: (row: any) => `${formatNum(row.win_rate)}%` },
              { key: "pnl", title: "PnL", render: (row: any) => formatNum(row.pnl) },
              { key: "signals", title: "Signals", render: (row: any) => formatNum(row.signals, 0) },
            ]}
          />
        </Panel>

        <Panel title="System Health">
          <DataTable
            rows={healthRows}
            emptyText="No system health rows."
            columns={[
              { key: "role", title: "Role", render: (row: any) => row.role },
              {
                key: "online",
                title: "Online",
                render: (row: any) => <StatusPill text={row.online ? "YES" : "NO"} tone={row.online ? "good" : "bad"} />,
              },
              { key: "latency", title: "Latency ms", render: (row: any) => formatNum(row.latency, 0) },
              { key: "last_seen_seconds", title: "Last Seen (s)", render: (row: any) => formatNum(row.last_seen_seconds, 0) },
              { key: "error_count", title: "Errors", render: (row: any) => formatNum(row.error_count, 0) },
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
