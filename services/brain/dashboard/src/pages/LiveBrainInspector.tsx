import { useEffect, useMemo, useState } from "react";
import { fetchBrainInspectorDecisionTraces, fetchBrainInspectorFeaturesSample, fetchBrainInspectorOverview } from "../api/inspector";
import type { UnifiedRole } from "../api/unified";
import { DataTable, Panel, SectionHeader, StatusBadge, StatusPill, formatNum } from "../components/mina";

type InspectorRole = "all" | UnifiedRole;

function pickField(row: any, keys: string[], fallback: any = "—"): any {
  for (const k of keys) {
    const direct = row?.[k];
    if (direct !== undefined && direct !== null && direct !== "") return direct;
    const tr = row?.trace;
    if (tr && typeof tr === "object") {
      const tv = tr[k];
      if (tv !== undefined && tv !== null && tv !== "") return tv;
    }
  }
  return fallback;
}

function vetoReason(row: any): string {
  const raw = pickField(row, ["veto_reason", "veto_reasons", "reject_reason", "reason"], "");
  if (Array.isArray(raw)) return raw.map((x) => String(x)).join(", ");
  return String(raw || "");
}

function gatekeeperOut(row: any): string {
  const gate = String(pickField(row, ["gatekeeper", "gate", "decision"], "abstain")).toUpperCase();
  if (gate.includes("REJECT")) return "reject";
  if (gate.includes("ABSTAIN") || gate.includes("WAIT")) return "abstain";
  if (gate.includes("BUY") || gate.includes("LONG")) return "buy";
  if (gate.includes("SELL") || gate.includes("SHORT")) return "sell";
  return gate.toLowerCase();
}

export default function LiveBrainInspector(props: { initialRole?: UnifiedRole; lockRole?: boolean }) {
  const [role, setRole] = useState<InspectorRole>((props.initialRole || "all") as InspectorRole);
  const [traceId, setTraceId] = useState("");
  const [decisionId, setDecisionId] = useState("");
  const [limit, setLimit] = useState("120");
  const [message, setMessage] = useState("");

  const [overview, setOverview] = useState<any>(null);
  const [features, setFeatures] = useState<any[]>([]);
  const [traces, setTraces] = useState<any[]>([]);

  useEffect(() => {
    if (props.initialRole) setRole(props.initialRole as InspectorRole);
  }, [props.initialRole]);

  const load = async () => {
    try {
      const lim = Math.max(20, Math.min(500, Number(limit) || 120));
      const [ov, ft, tr] = await Promise.all([
        fetchBrainInspectorOverview(role),
        fetchBrainInspectorFeaturesSample(40),
        fetchBrainInspectorDecisionTraces({
          role,
          trace_id: traceId.trim() || undefined,
          decision_id: decisionId.trim() ? Number(decisionId) : undefined,
          limit: lim,
        }),
      ]);
      setOverview(ov || {});
      setFeatures(Array.isArray(ft?.items) ? ft.items : []);
      setTraces(Array.isArray(tr?.items) ? tr.items : []);
      setMessage("");
    } catch (err: any) {
      setMessage(err?.message || "Failed to load brain inspector.");
    }
  };

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  const roleRows = useMemo(() => {
    const rows = overview?.roles || {};
    return Object.entries(rows).map(([r, v]) => ({ role: r, ...(v as any) }));
  }, [overview]);

  const latestDecisions = useMemo(() => {
    return traces
      .filter((row) => !String(gatekeeperOut(row)).includes("reject"))
      .slice(0, 40);
  }, [traces]);

  const latestRejections = useMemo(() => {
    return traces
      .filter((row) => {
        const g = gatekeeperOut(row);
        return g === "reject" || g === "abstain";
      })
      .slice(0, 40);
  }, [traces]);

  const topCandidates = useMemo(() => {
    const ranked = [...traces];
    ranked.sort((a, b) => {
      const sa = Number(pickField(a, ["score", "final_score", "confidence"], 0));
      const sb = Number(pickField(b, ["score", "final_score", "confidence"], 0));
      return sb - sa;
    });
    return ranked.slice(0, 40);
  }, [traces]);

  const copyTrace = async (trace: string) => {
    try {
      await navigator.clipboard.writeText(trace);
      setMessage(`trace_id copied: ${trace}`);
    } catch {
      setMessage("Could not copy trace_id.");
    }
  };

  return (
    <div>
      <SectionHeader
        title="Live Brain Inspector"
        subtitle="Why the bot buys/rejects now: decisions, rejections, candidates, and feature snapshots."
        right={message ? <span className="muted">{message}</span> : null}
      />

      <Panel title="Filters">
        <div className="filters-row">
          <select
            data-testid="inspector-role"
            className="dark-select"
            value={role}
            disabled={Boolean(props.lockRole)}
            onChange={(e) => setRole(e.target.value as InspectorRole)}
          >
            <option value="all">all</option>
            <option value="paper">paper</option>
            <option value="live">live</option>
            <option value="pump">pump</option>
          </select>
          <input data-testid="inspector-trace-id" className="dark-input" placeholder="trace_id contains" value={traceId} onChange={(e) => setTraceId(e.target.value)} />
          <input data-testid="inspector-decision-id" className="dark-input" placeholder="decision id" value={decisionId} onChange={(e) => setDecisionId(e.target.value)} />
          <input data-testid="inspector-limit" className="dark-input" placeholder="limit" value={limit} onChange={(e) => setLimit(e.target.value)} style={{ width: 110 }} />
          <button data-testid="inspector-refresh" className="action-btn primary" onClick={() => void load()}>
            Refresh
          </button>
        </div>
      </Panel>

      <Panel title="Overview">
        <DataTable
          rows={roleRows}
          emptyText="No role stats available yet."
          columns={[
            { key: "role", title: "Role", render: (row: any) => row.role },
            { key: "trades", title: "Trades", render: (row: any) => formatNum(row.trades, 0) },
            { key: "wins", title: "Wins", render: (row: any) => formatNum(row.wins, 0) },
            { key: "losses", title: "Losses", render: (row: any) => formatNum(row.losses, 0) },
            { key: "win_rate", title: "Win Rate", render: (row: any) => `${formatNum(row.win_rate)}%` },
            {
              key: "expectancy",
              title: "Expectancy",
              render: (row: any) => <StatusPill text={formatNum(row.expectancy, 6)} tone={Number(row.expectancy) >= 0 ? "good" : "bad"} />,
            },
          ]}
        />
      </Panel>

      <div className="grid-2">
        <Panel title="Latest Decisions" subtitle="Live stream via periodic refresh.">
          <DataTable
            rows={latestDecisions}
            pageSize={10}
            emptyText="No decisions yet."
            columns={[
              { key: "symbol", title: "Symbol", render: (row: any) => pickField(row, ["symbol"], "—") },
              { key: "timeframe", title: "Timeframe", render: (row: any) => pickField(row, ["timeframe", "interval"], "—") },
              { key: "side", title: "Side", render: (row: any) => pickField(row, ["side", "suggestion", "ai_vote"], "—") },
              { key: "confidence", title: "Confidence", render: (row: any) => formatNum(pickField(row, ["confidence", "ai_confidence"], 0), 4) },
              { key: "score", title: "Score", render: (row: any) => formatNum(pickField(row, ["score", "final_score"], 0), 4) },
              { key: "regime", title: "Regime", render: (row: any) => pickField(row, ["regime_label", "micro_regime_label"], "—") },
              {
                key: "gatekeeper",
                title: "Gatekeeper",
                render: (row: any) => {
                  const out = gatekeeperOut(row);
                  const tone = out === "buy" || out === "sell" ? "good" : out === "reject" ? "bad" : "warn";
                  return <StatusBadge text={out} tone={tone as any} />;
                },
              },
              { key: "strategy", title: "Strategy", render: (row: any) => pickField(row, ["strategy", "strategy_tag"], "—") },
            ]}
          />
        </Panel>

        <Panel title="Latest Rejections" subtitle="Veto reasons and abstain cases.">
          <DataTable
            rows={latestRejections}
            pageSize={10}
            emptyText="No rejections yet."
            columns={[
              { key: "symbol", title: "Symbol", render: (row: any) => pickField(row, ["symbol"], "—") },
              { key: "timeframe", title: "Timeframe", render: (row: any) => pickField(row, ["timeframe", "interval"], "—") },
              { key: "score", title: "Score", render: (row: any) => formatNum(pickField(row, ["score", "final_score"], 0), 4) },
              { key: "confidence", title: "Confidence", render: (row: any) => formatNum(pickField(row, ["confidence", "ai_confidence"], 0), 4) },
              { key: "gatekeeper", title: "Gatekeeper", render: (row: any) => <StatusBadge text={gatekeeperOut(row)} tone="bad" /> },
              { key: "veto", title: "Veto Reasons", render: (row: any) => vetoReason(row) || "—" },
            ]}
          />
        </Panel>
      </div>

      <div className="grid-2">
        <Panel title="Top Candidates">
          <DataTable
            rows={topCandidates}
            pageSize={10}
            emptyText="No candidate rows."
            columns={[
              { key: "symbol", title: "Symbol", render: (row: any) => pickField(row, ["symbol"], "—") },
              { key: "score", title: "Score", render: (row: any) => formatNum(pickField(row, ["score", "final_score"], 0), 4) },
              { key: "confidence", title: "Confidence", render: (row: any) => formatNum(pickField(row, ["confidence", "ai_confidence"], 0), 4) },
              { key: "regime", title: "Regime", render: (row: any) => pickField(row, ["regime_label", "micro_regime_label"], "—") },
              { key: "rsi", title: "RSI", render: (row: any) => formatNum(pickField(row, ["rsi"], 0), 4) },
              { key: "adx", title: "ADX", render: (row: any) => formatNum(pickField(row, ["adx"], 0), 4) },
              { key: "atr_pct", title: "ATR%", render: (row: any) => formatNum(pickField(row, ["atr_pct", "atr_percent"], 0), 4) },
              { key: "funding", title: "Funding", render: (row: any) => formatNum(pickField(row, ["funding"], 0), 6) },
              { key: "oi_change", title: "OI Change", render: (row: any) => formatNum(pickField(row, ["oi_change"], 0), 6) },
              { key: "pump_score", title: "Pump Score", render: (row: any) => formatNum(pickField(row, ["pump_score"], 0), 2) },
            ]}
          />
        </Panel>

        <Panel title="Feature Store Samples">
          <DataTable
            rows={features}
            pageSize={10}
            emptyText="No feature rows yet."
            columns={[
              { key: "id", title: "ID", render: (row: any) => row.id ?? "—" },
              { key: "trade_id", title: "Trade ID", render: (row: any) => row.trade_id ?? "—" },
              { key: "role", title: "Role", render: (row: any) => row.role || "—" },
              { key: "symbol", title: "Symbol", render: (row: any) => row.symbol || "—" },
              {
                key: "trace_id",
                title: "trace_id",
                render: (row: any) => {
                  const tr = String(row.trace_id || row.trace?.trace_id || "");
                  if (!tr) return "—";
                  return (
                    <div className="filters-row">
                      <span>{tr}</span>
                      <button data-testid="inspector-copy-trace" className="mini-btn" onClick={() => void copyTrace(tr)}>
                        Copy
                      </button>
                    </div>
                  );
                },
              },
              { key: "created_at", title: "Time", render: (row: any) => row.created_at || "—" },
            ]}
          />
        </Panel>
      </div>
    </div>
  );
}
