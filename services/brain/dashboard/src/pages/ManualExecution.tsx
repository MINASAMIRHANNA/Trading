import { useEffect, useMemo, useState } from "react";
import { executeManualTrade } from "../api/manual";
import { fetchUnifiedCommandsHistory, type UnifiedRole } from "../api/unified";
import { DataTable, KpiCard, Panel, SectionHeader, StatusBadge } from "../components/mina";
import { requestLiveGuard } from "../utils/liveGuard";

function newTraceId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return `trace-${Date.now()}-${Math.floor(Math.random() * 1_000_000)}`;
  }
}

export default function ManualExecution(props: { initialRole?: UnifiedRole; lockRole?: boolean }) {
  const [role, setRole] = useState<UnifiedRole>(props.initialRole || "paper");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [amountUsd, setAmountUsd] = useState("100");
  const [market, setMarket] = useState<"futures" | "spot">("futures");
  const [direction, setDirection] = useState<"LONG" | "SHORT">("LONG");
  const [timeInForce, setTimeInForce] = useState("MARKET");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastResult, setLastResult] = useState<any>(null);
  const [commandStatus, setCommandStatus] = useState<any>(null);

  useEffect(() => {
    if (props.initialRole) setRole(props.initialRole);
  }, [props.initialRole]);

  const commandId = Number(lastResult?.command_id || 0);

  useEffect(() => {
    if (!commandId) {
      setCommandStatus(null);
      return;
    }
    let stopped = false;
    const tick = async () => {
      try {
        const out = await fetchUnifiedCommandsHistory(role, 80);
        const items = Array.isArray(out?.items) ? out.items : [];
        const row = items.find((x: any) => Number(x?.id || 0) === commandId);
        if (!stopped) setCommandStatus(row || null);
      } catch {
        if (!stopped) setCommandStatus(null);
      }
    };
    void tick();
    const id = setInterval(() => void tick(), 2000);
    return () => {
      stopped = true;
      clearInterval(id);
    };
  }, [commandId, role]);

  const lifecycle = useMemo(() => {
    if (!lastResult) return "idle";
    if (String(lastResult?.lifecycle || "").toLowerCase() === "executed") return "executed";
    const st = String(commandStatus?.status || "").toUpperCase();
    if (!st) return "queued";
    if (["DONE", "EXECUTED", "COMPLETED", "SUCCESS"].includes(st)) return "executed";
    if (["ACKED", "CLAIMED", "IN_PROGRESS", "RUNNING"].includes(st)) return "acked";
    return "queued";
  }, [commandStatus, lastResult]);

  const runExecute = async () => {
    const s = symbol.trim().toUpperCase();
    const amt = Number(amountUsd);
    if (!s) {
      setMessage("Symbol is required.");
      return;
    }
    if (!Number.isFinite(amt) || amt <= 0) {
      setMessage("Amount must be greater than 0.");
      return;
    }

    let guard: Record<string, any> = {};
    if (role === "live") {
      const payload = await requestLiveGuard(`Execute ${s} ${direction} (${market})`);
      if (!payload) return;
      guard = payload;
    }

    setBusy(true);
    setMessage("");
    try {
      const traceId = newTraceId();
      const result = await executeManualTrade({
        role,
        symbol: s,
        amount_usd: amt,
        market,
        direction,
        time_in_force: timeInForce,
        trace_id: traceId,
        ...(guard || {}),
      } as any);
      setLastResult(result || {});
      if (result?.trade_id) {
        setMessage(`Manual execution complete. Open trade #${result.trade_id}`);
      } else {
        setMessage("Manual execution command queued.");
      }
    } catch (err: any) {
      setMessage(err?.message || "Manual execution failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <SectionHeader
        title="Manual Execution"
        subtitle="Execute a manual trade through Gateway only. Paper mode is simulated-safe; live requires confirmation and keys."
        right={message ? <span className="muted">{message}</span> : null}
      />

      <Panel title="Execution Form">
        <div className="filters-row">
          {!props.lockRole ? (
            <select data-testid="manual-exec-role" className="dark-select" value={role} onChange={(e) => setRole(e.target.value as UnifiedRole)}>
              <option value="paper">paper</option>
              <option value="live">live</option>
            </select>
          ) : (
            <StatusBadge text={`role=${role}`} tone={role === "live" ? "warn" : "info"} />
          )}
          <input
            data-testid="manual-exec-symbol"
            className="dark-input"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="BTCUSDT"
          />
          <input
            data-testid="manual-exec-amount"
            className="dark-input"
            value={amountUsd}
            onChange={(e) => setAmountUsd(e.target.value)}
            placeholder="Amount (USD)"
          />
          <select data-testid="manual-exec-market" className="dark-select" value={market} onChange={(e) => setMarket(e.target.value as "futures" | "spot")}>
            <option value="futures">Futures</option>
            <option value="spot">Spot</option>
          </select>
          <select data-testid="manual-exec-direction" className="dark-select" value={direction} onChange={(e) => setDirection(e.target.value as "LONG" | "SHORT")}>
            <option value="LONG">LONG / BUY</option>
            <option value="SHORT">SHORT / SELL</option>
          </select>
          <input
            data-testid="manual-exec-tif"
            className="dark-input"
            value={timeInForce}
            onChange={(e) => setTimeInForce(e.target.value.toUpperCase())}
            placeholder="MARKET"
          />
          <button data-testid="manual-exec-submit" className="action-btn primary" disabled={busy} onClick={() => void runExecute()}>
            Execute Trade
          </button>
        </div>
        <div className="filters-row" style={{ marginTop: 8 }}>
          {role === "live" ? (
            <StatusBadge text="LIVE warnings enabled (double-confirm / PIN)" tone="warn" />
          ) : (
            <StatusBadge text="Paper/Testnet simulation mode" tone="good" />
          )}
        </div>
      </Panel>

      <Panel title="Command Lifecycle">
        <div className="kpi-grid">
          <KpiCard label="trace_id" value={lastResult?.trace_id || "—"} />
          <KpiCard label="command_id" value={lastResult?.command_id || "—"} />
          <KpiCard label="trade_id" value={lastResult?.trade_id || "—"} />
          <KpiCard
            label="status"
            value={lifecycle}
            tone={lifecycle === "executed" ? "good" : lifecycle === "acked" ? "warn" : "info"}
          />
        </div>
      </Panel>

      <Panel title="Last Response">
        <DataTable
          rows={lastResult ? [lastResult] : []}
          emptyText="No manual execution yet."
          enableCopy
          columns={[
            { key: "role", title: "Role", render: (row: any) => row.role || "—" },
            { key: "symbol", title: "Symbol", render: () => symbol.trim().toUpperCase() || "—" },
            { key: "command_id", title: "Command", render: (row: any) => row.command_id ?? "—" },
            { key: "trade_id", title: "Trade", render: (row: any) => row.trade_id ?? "—" },
            { key: "trace_id", title: "trace_id", render: (row: any) => row.trace_id || "—" },
            {
              key: "lifecycle",
              title: "Lifecycle",
              render: () => (
                <StatusBadge
                  text={lifecycle}
                  tone={lifecycle === "executed" ? "good" : lifecycle === "acked" ? "warn" : "info"}
                />
              ),
            },
          ]}
        />
      </Panel>
    </div>
  );
}
