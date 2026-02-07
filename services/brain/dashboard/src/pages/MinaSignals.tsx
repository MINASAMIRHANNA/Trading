import { useEffect, useMemo, useState } from "react";
import {
  type UnifiedRole,
  approveUnifiedSignal,
  fetchUnifiedSignalDecision,
  fetchUnifiedSignals,
  rejectUnifiedSignal,
  type UnifiedSignalsQuery,
} from "../api/unified";
import { DataTable, Panel, SectionHeader, StatusBadge, Tabs } from "../components/mina";
import { requestLiveGuard } from "../utils/liveGuard";

type TabKey = "inbox" | "all";

function localDateTimeToUtcIso(value: string): string | undefined {
  const txt = String(value || "").trim();
  if (!txt) return undefined;
  const dt = new Date(txt);
  if (!Number.isFinite(dt.getTime())) return undefined;
  return dt.toISOString();
}

function toneForStatus(value: unknown): "neutral" | "good" | "bad" | "warn" | "info" {
  const s = String(value || "").toUpperCase();
  if (s === "APPROVED" || s === "EXECUTED") return "good";
  if (s === "REJECTED") return "bad";
  if (s === "PENDING_APPROVAL" || s === "PENDING" || s === "RECEIVED") return "warn";
  return "neutral";
}

export default function MinaSignals() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [tab, setTab] = useState<TabKey>("inbox");
  const [status, setStatus] = useState("all");
  const [source, setSource] = useState("");
  const [symbol, setSymbol] = useState("");
  const [timeframe, setTimeframe] = useState("");
  const [strategy, setStrategy] = useState("");
  const [fromLocal, setFromLocal] = useState("");
  const [toLocal, setToLocal] = useState("");
  const [limit, setLimit] = useState("100");

  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<any[]>([]);
  const [apiError, setApiError] = useState("");
  const [message, setMessage] = useState("");
  const [busySignalId, setBusySignalId] = useState<number | null>(null);

  const [decisionOpen, setDecisionOpen] = useState(false);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [decisionData, setDecisionData] = useState<any>(null);
  const [decisionErr, setDecisionErr] = useState("");

  const canAct = (row: any) => {
    const s = String(row?.status || "").toUpperCase();
    return s === "PENDING_APPROVAL" || s === "PENDING" || s === "RECEIVED";
  };

  const query = useMemo<UnifiedSignalsQuery>(
    () => ({
      limit: Math.max(1, Math.min(500, Number(limit || 100))),
      status: tab === "inbox" ? "PENDING_APPROVAL" : status,
      source: source.trim() || undefined,
      symbol: symbol.trim().toUpperCase() || undefined,
      timeframe: timeframe.trim() || undefined,
      strategy: strategy.trim() || undefined,
      from_ts: localDateTimeToUtcIso(fromLocal),
      to_ts: localDateTimeToUtcIso(toLocal),
    }),
    [fromLocal, limit, source, status, strategy, symbol, tab, timeframe, toLocal],
  );

  const load = async () => {
    setLoading(true);
    setApiError("");
    try {
      const out = await fetchUnifiedSignals(role, query);
      setItems(Array.isArray(out?.items) ? out.items : []);
      setMessage("");
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      const msg = detail ? JSON.stringify(detail) : String(err?.message || "request_failed");
      setItems([]);
      setApiError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role, query]);

  const approve = async (row: any) => {
    const signalId = Number(row?.id || 0);
    if (!signalId) return;
    const guard = role === "live" ? await requestLiveGuard(`Approve signal #${signalId}`) : null;
    if (role === "live" && !guard) return;
    setBusySignalId(signalId);
    try {
      const out = await approveUnifiedSignal(role, signalId, "Approved via Unified Dashboard", undefined, guard || undefined);
      setMessage(`Approved signal #${signalId} (trace_id=${out?.trace_id || "n/a"})`);
      await load();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setApiError(detail ? JSON.stringify(detail) : String(err?.message || "approve_failed"));
    } finally {
      setBusySignalId(null);
    }
  };

  const reject = async (row: any) => {
    const signalId = Number(row?.id || 0);
    if (!signalId) return;
    const guard = role === "live" ? await requestLiveGuard(`Reject signal #${signalId}`) : null;
    if (role === "live" && !guard) return;
    setBusySignalId(signalId);
    try {
      const out = await rejectUnifiedSignal(role, signalId, "rejected", "Rejected via Unified Dashboard", guard || undefined);
      setMessage(`Rejected signal #${signalId} (trace_id=${out?.trace_id || "n/a"})`);
      await load();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setApiError(detail ? JSON.stringify(detail) : String(err?.message || "reject_failed"));
    } finally {
      setBusySignalId(null);
    }
  };

  const openDecision = async (signalId: number) => {
    setDecisionOpen(true);
    setDecisionLoading(true);
    setDecisionErr("");
    setDecisionData(null);
    try {
      const out = await fetchUnifiedSignalDecision(role, signalId);
      setDecisionData(out);
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      setDecisionErr(detail ? JSON.stringify(detail) : String(err?.message || "decision_failed"));
    } finally {
      setDecisionLoading(false);
    }
  };

  const emptyText = apiError
    ? `API unreachable: ${apiError}`
    : loading
      ? "Loading..."
      : "No signals yet";

  return (
    <div>
      <SectionHeader
        title="Signals"
        subtitle="Paper/live inbox managed by Unified Dashboard only. Reads/writes go through Gateway."
        right={message ? <span className="muted">{message}</span> : null}
      />

      <Panel title="Scope">
        <div className="filters-row">
          <select data-testid="signals-role" className="dark-select" value={role} onChange={(e) => setRole(e.target.value as UnifiedRole)}>
            <option value="paper">paper</option>
            <option value="live">live</option>
            <option value="pump">pump</option>
          </select>
          <input
            data-testid="signals-limit"
            className="dark-input"
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            placeholder="limit"
            style={{ width: 100 }}
          />
          <button data-testid="signals-refresh" className="action-btn primary" onClick={() => void load()} disabled={loading}>
            Refresh
          </button>
          {role === "live" ? <StatusBadge text="LIVE safety guard active" tone="warn" /> : null}
        </div>
      </Panel>

      <Panel title="Views">
        <Tabs
          value={tab}
          onChange={(next) => setTab(next as TabKey)}
          items={[
            { key: "inbox", label: <span data-testid="signals-tab-inbox">Inbox (PENDING_APPROVAL)</span> },
            { key: "all", label: <span data-testid="signals-tab-all">All signals</span> },
          ]}
        />
      </Panel>

      <Panel title="Filters">
        <div className="filters-row">
          <select
            data-testid="signals-status-filter"
            className="dark-select"
            value={tab === "inbox" ? "PENDING_APPROVAL" : status}
            disabled={tab === "inbox"}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="all">all</option>
            <option value="PENDING_APPROVAL">PENDING_APPROVAL</option>
            <option value="RECEIVED">RECEIVED</option>
            <option value="APPROVED">APPROVED</option>
            <option value="REJECTED">REJECTED</option>
            <option value="EXECUTED">EXECUTED</option>
          </select>
          <input data-testid="signals-source-filter" className="dark-input" placeholder="source" value={source} onChange={(e) => setSource(e.target.value)} />
          <input data-testid="signals-symbol-filter" className="dark-input" placeholder="symbol" value={symbol} onChange={(e) => setSymbol(e.target.value)} />
          <input data-testid="signals-timeframe-filter" className="dark-input" placeholder="timeframe" value={timeframe} onChange={(e) => setTimeframe(e.target.value)} />
          <input data-testid="signals-strategy-filter" className="dark-input" placeholder="strategy" value={strategy} onChange={(e) => setStrategy(e.target.value)} />
          <input data-testid="signals-from-filter" className="dark-input" type="datetime-local" value={fromLocal} onChange={(e) => setFromLocal(e.target.value)} />
          <input data-testid="signals-to-filter" className="dark-input" type="datetime-local" value={toLocal} onChange={(e) => setToLocal(e.target.value)} />
        </div>
      </Panel>

      {apiError ? (
        <Panel title="Connection">
          <StatusBadge text="API unreachable" tone="bad" />
          <pre className="code-block" style={{ marginTop: 10 }}>{apiError}</pre>
        </Panel>
      ) : null}

      <Panel title={tab === "inbox" ? "Signals Inbox" : "All Signals"}>
        <DataTable
          rows={items}
          pageSize={20}
          emptyText={emptyText}
          columns={[
            {
              key: "id",
              title: "ID",
              render: (row: any) => (
                <span data-testid={`signal-id-${row?.id}`}>
                  {row?.id ?? "—"}
                </span>
              ),
            },
            { key: "received_at", title: "Time (UTC)", render: (row: any) => row?.received_at || row?.created_at || "—" },
            {
              key: "status",
              title: "Status",
              render: (row: any) => <StatusBadge text={String(row?.status || "UNKNOWN")} tone={toneForStatus(row?.status)} />,
            },
            { key: "source", title: "Source", render: (row: any) => row?.source || "—" },
            { key: "symbol", title: "Symbol", render: (row: any) => row?.symbol || "—" },
            { key: "side", title: "Side", render: (row: any) => row?.side || "—" },
            { key: "timeframe", title: "Timeframe", render: (row: any) => row?.timeframe || "—" },
            { key: "strategy", title: "Strategy", render: (row: any) => row?.strategy || "—" },
            {
              key: "confidence",
              title: "Confidence",
              render: (row: any) => {
                const v = Number(row?.confidence);
                if (!Number.isFinite(v)) return "—";
                return v.toFixed(4);
              },
            },
            {
              key: "actions",
              title: "Actions",
              render: (row: any) => {
                const id = Number(row?.id || 0);
                const disabled = !id || loading || busySignalId === id;
                const actionable = canAct(row);
                return (
                  <div className="filters-row">
                    <button
                      data-testid={`signals-decision-${id}`}
                      className="mini-btn"
                      disabled={disabled}
                      onClick={() => void openDecision(id)}
                    >
                      Decision
                    </button>
                    <button
                      data-testid={`signals-approve-${id}`}
                      className="mini-btn"
                      disabled={disabled || !actionable}
                      onClick={() => void approve(row)}
                    >
                      Approve
                    </button>
                    <button
                      data-testid={`signals-reject-${id}`}
                      className="mini-btn"
                      disabled={disabled || !actionable}
                      onClick={() => void reject(row)}
                    >
                      Reject
                    </button>
                  </div>
                );
              },
            },
          ]}
        />
      </Panel>

      {decisionOpen ? (
        <Panel title="Decision Detail" right={<button className="action-btn" onClick={() => setDecisionOpen(false)}>Close</button>}>
          {decisionLoading ? <div className="muted">Loading decision...</div> : null}
          {decisionErr ? <pre className="code-block">{decisionErr}</pre> : null}
          {!decisionLoading && !decisionErr ? <pre className="code-block">{JSON.stringify(decisionData || {}, null, 2)}</pre> : null}
        </Panel>
      ) : null}
    </div>
  );
}
