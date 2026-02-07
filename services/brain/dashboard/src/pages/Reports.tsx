import { useEffect, useMemo, useState } from "react";
import {
  fetchDailySummary,
  fetchDeepAudit,
  exportReport,
  fetchAnalytics,
  fetchAuditTrace,
  fetchDataQuality,
  fetchFeesSlippage,
  fetchPaperArena,
  fetchPnlBreakdown,
  fetchRiskTimeline,
  fetchStrategyCompare,
  fetchStrategyPerformance,
} from "../api/reports";
import { DataTable, KpiCard, Panel, SectionHeader, StatusBadge, formatNum, toneFromValue } from "../components/mina";

export default function Reports() {
  const [role, setRole] = useState("paper");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [period, setPeriod] = useState("daily");
  const [traceId, setTraceId] = useState("");
  const [message, setMessage] = useState("");
  const [paperArena, setPaperArena] = useState<any>(null);
  const [analytics, setAnalytics] = useState<any>(null);
  const [quality, setQuality] = useState<any>(null);
  const [pnlBreakdown, setPnlBreakdown] = useState<any>(null);
  const [strategyPerf, setStrategyPerf] = useState<any>(null);
  const [fees, setFees] = useState<any>(null);
  const [risk, setRisk] = useState<any>(null);
  const [traceData, setTraceData] = useState<any>(null);
  const [dailySummary, setDailySummary] = useState<any>(null);
  const [strategyCompare, setStrategyCompare] = useState<any>(null);
  const [deepAudit, setDeepAudit] = useState<any>(null);

  const load = async () => {
    try {
      const [pa, an, dq, pb, sp, fs, rt, da, ds, sc] = await Promise.all([
        fetchPaperArena({ from: from || undefined, to: to || undefined }),
        fetchAnalytics({ from: from || undefined, to: to || undefined }),
        fetchDataQuality({ role, from: from || undefined, to: to || undefined }),
        fetchPnlBreakdown({ role, from: from || undefined, to: to || undefined, period }),
        fetchStrategyPerformance({ role, from: from || undefined, to: to || undefined }),
        fetchFeesSlippage({ role, from: from || undefined, to: to || undefined }),
        fetchRiskTimeline({ role, limit: 100 }),
        fetchDeepAudit({ role, limit: 100 }),
        fetchDailySummary({ role }),
        fetchStrategyCompare({ role }),
      ]);
      setPaperArena(pa);
      setAnalytics(an);
      setQuality(dq);
      setPnlBreakdown(pb);
      setStrategyPerf(sp);
      setFees(fs);
      setRisk(rt);
      setDeepAudit(da);
      setDailySummary(ds);
      setStrategyCompare(sc);
    } catch (err: any) {
      setMessage(err?.message || "Failed to load reports");
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role, from, to, period]);

  const kpis = useMemo(() => {
    const overall = paperArena?.summary || paperArena?.overall || {};
    return [
      { label: "Arena Trades", value: overall?.trades ?? overall?.total_trades },
      { label: "Arena Realized", value: overall?.realized_pnl, tone: toneFromValue(overall?.realized_pnl) },
      { label: "Analytics Trades", value: analytics?.trades ?? analytics?.summary?.total_trades },
      { label: "Win Rate", value: analytics?.win_rate, suffix: "%" },
      { label: "Expectancy", value: analytics?.expectancy, tone: toneFromValue(analytics?.expectancy) },
      { label: "Avg PnL", value: analytics?.avg_pnl, tone: toneFromValue(analytics?.avg_pnl) },
    ];
  }, [analytics, paperArena]);

  const exportJson = async (type: string) => {
    try {
      const data = await exportReport({ type, format: "json", role, from, to });
      setMessage(`Export JSON ready for ${type} (${Object.keys(data || {}).length} keys).`);
    } catch (err: any) {
      setMessage(err?.message || "Export failed");
    }
  };

  const exportCsv = async (type: string) => {
    try {
      await exportReport({ type, format: "csv", role, from, to });
      setMessage(`CSV export requested for ${type}.`);
    } catch (err: any) {
      setMessage(err?.message || "CSV export failed");
    }
  };

  const loadTrace = async () => {
    if (!traceId.trim()) {
      setMessage("trace_id is required");
      return;
    }
    try {
      setTraceData(await fetchAuditTrace(traceId.trim()));
    } catch (err: any) {
      setMessage(err?.message || "Trace lookup failed");
    }
  };

  const latencyRows = (traceData?.audit || []).map((item: any) => ({
    action: item.action || "—",
    target: item.target_id || "—",
    role: item.role || "—",
    trace: item.trace_id || "—",
    ts: item.created_at || "—",
  }));

  return (
    <div>
      <SectionHeader
        title="Reports"
        subtitle="Paper Arena, analytics, audit trace, and additional operations reports."
        right={message ? <span className="muted">{message}</span> : null}
      />

      <Panel title="Filters">
        <div className="filters-row">
          <select className="dark-select" value={role} onChange={(e) => setRole(e.target.value)}>
            {["paper", "live", "pump"].map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <input className="dark-input" placeholder="From UTC (ISO)" value={from} onChange={(e) => setFrom(e.target.value)} />
          <input className="dark-input" placeholder="To UTC (ISO)" value={to} onChange={(e) => setTo(e.target.value)} />
          <select className="dark-select" value={period} onChange={(e) => setPeriod(e.target.value)}>
            <option value="daily">daily</option>
            <option value="weekly">weekly</option>
          </select>
          <button className="action-btn primary" onClick={() => void load()}>
            Refresh
          </button>
        </div>
      </Panel>

      <Panel title="Summary KPIs">
        <div className="kpi-grid">
          {kpis.map((k) => (
            <KpiCard
              key={k.label}
              label={k.label}
              value={typeof k.value === "number" ? `${formatNum(k.value)}${k.suffix || ""}` : k.value ?? "—"}
              tone={(k.tone as any) || "neutral"}
            />
          ))}
        </div>
      </Panel>

      <div className="grid-2">
        <Panel title="Paper Arena Report" subtitle="Best/worst symbols + export">
          <div className="filters-row" style={{ marginBottom: 10 }}>
            <button className="action-btn" onClick={() => void exportJson("paper-arena")}>
              Export JSON
            </button>
            <button className="action-btn" onClick={() => void exportCsv("paper-arena")}>
              Export CSV
            </button>
          </div>
          <DataTable
            rows={Object.entries((paperArena?.summary || paperArena?.overall || {}) as Record<string, unknown>).map(([k, v]) => ({ k, v }))}
            columns={[
              { key: "k", title: "Metric", render: (row: any) => row.k },
              { key: "v", title: "Value", render: (row: any) => (typeof row.v === "number" ? formatNum(row.v, 4) : String(row.v ?? "—")) },
            ]}
            emptyText="No arena data yet."
          />
        </Panel>

        <Panel title="Data Quality">
          <DataTable
            rows={Object.entries((quality?.roles?.[role] || quality || {}) as Record<string, unknown>).map(([k, v]) => ({ k, v }))}
            columns={[
              { key: "k", title: "Metric", render: (row: any) => row.k },
              { key: "v", title: "Value", render: (row: any) => (typeof row.v === "object" ? JSON.stringify(row.v) : String(row.v ?? "—")) },
            ]}
            emptyText="No quality data."
          />
        </Panel>
      </div>

      <Panel title="PnL Breakdown">
        <DataTable
          rows={pnlBreakdown?.items || []}
          emptyText="Insufficient data for PnL breakdown."
          columns={[
            { key: "bucket", title: "Bucket", render: (row: any) => row.bucket || "—" },
            { key: "trades", title: "Trades", render: (row: any) => row.trades ?? "—" },
            {
              key: "pnl",
              title: "PnL",
              render: (row: any) => <StatusBadge text={formatNum(row.pnl)} tone={toneFromValue(row.pnl)} />,
            },
          ]}
        />
      </Panel>

      <div className="grid-2">
        <Panel title="Fees Breakdown / Slippage Report">
          <DataTable
            rows={Object.entries((fees?.data || fees || {}) as Record<string, unknown>).map(([k, v]) => ({ k, v }))}
            emptyText="Insufficient data for fees/slippage."
            columns={[
              { key: "k", title: "Metric", render: (row: any) => row.k },
              { key: "v", title: "Value", render: (row: any) => (typeof row.v === "number" ? formatNum(row.v, 6) : String(row.v ?? "—")) },
            ]}
          />
        </Panel>

        <Panel title="Strategy Performance">
          <DataTable
            rows={strategyPerf?.items || []}
            emptyText="Insufficient data for strategy performance."
            columns={[
              { key: "strategy", title: "Strategy", render: (row: any) => row.strategy || "—" },
              { key: "trades", title: "Trades", render: (row: any) => row.trades ?? "—" },
              {
                key: "pnl",
                title: "PnL",
                render: (row: any) => <StatusBadge text={formatNum(row.pnl)} tone={toneFromValue(row.pnl)} />,
              },
              { key: "avg", title: "Avg PnL", render: (row: any) => formatNum(row.avg_pnl) },
            ]}
          />
        </Panel>
      </div>

      <Panel title="Trade Duration / Risk Events Timeline">
        <DataTable
          rows={risk?.items || []}
          emptyText="Insufficient data for risk timeline."
          columns={[
            { key: "ts", title: "Time", render: (row: any) => row.ts || row.created_at || "—" },
            { key: "level", title: "Level", render: (row: any) => <StatusBadge text={row.level || "—"} tone="warn" /> },
            { key: "message", title: "Message", render: (row: any) => row.message || "—" },
          ]}
        />
      </Panel>

      <Panel title="Deep Audit Lab (Signal -> Trade Latency)">
        <div className="filters-row" style={{ marginBottom: 10 }}>
          <input className="dark-input" placeholder="trace_id" value={traceId} onChange={(e) => setTraceId(e.target.value)} />
          <button className="action-btn primary" onClick={() => void loadTrace()}>
            Search Trace
          </button>
        </div>
        <DataTable
          rows={latencyRows}
          emptyText="Provide trace_id to inspect decision->signal->trade actions."
          columns={[
            { key: "action", title: "Action", render: (row: any) => row.action },
            { key: "role", title: "Role", render: (row: any) => row.role },
            { key: "target", title: "Target", render: (row: any) => row.target },
            { key: "trace", title: "Trace", render: (row: any) => row.trace },
            { key: "ts", title: "Time", render: (row: any) => row.ts },
          ]}
        />
      </Panel>

      <div className="grid-2">
        <Panel title="Daily Summary">
          <DataTable
            rows={Object.entries((dailySummary?.data || dailySummary || {}) as Record<string, unknown>).map(([k, v]) => ({ k, v }))}
            emptyText="Daily summary unavailable."
            columns={[
              { key: "k", title: "Metric", render: (row: any) => row.k },
              { key: "v", title: "Value", render: (row: any) => (typeof row.v === "object" ? JSON.stringify(row.v) : String(row.v ?? "—")) },
            ]}
          />
        </Panel>

        <Panel title="Strategy Compare">
          <DataTable
            rows={Object.entries((strategyCompare?.data || strategyCompare || {}) as Record<string, unknown>).map(([k, v]) => ({ k, v }))}
            emptyText="Strategy compare unavailable."
            columns={[
              { key: "k", title: "Metric", render: (row: any) => row.k },
              { key: "v", title: "Value", render: (row: any) => (typeof row.v === "object" ? JSON.stringify(row.v) : String(row.v ?? "—")) },
            ]}
          />
        </Panel>
      </div>

      <Panel title="Deep Audit Summary">
        <DataTable
          rows={Array.isArray(deepAudit?.audit) ? deepAudit.audit : []}
          emptyText="No deep audit events."
          columns={[
            { key: "created_at", title: "Time", render: (row: any) => row.created_at || "—" },
            { key: "role", title: "Role", render: (row: any) => row.role || "—" },
            { key: "action", title: "Action", render: (row: any) => row.action || "—" },
            { key: "target_id", title: "Target", render: (row: any) => row.target_id || "—" },
            { key: "trace_id", title: "trace_id", render: (row: any) => row.trace_id || "—" },
          ]}
        />
      </Panel>
    </div>
  );
}
