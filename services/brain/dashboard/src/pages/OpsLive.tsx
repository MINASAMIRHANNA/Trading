import { useEffect, useMemo, useRef, useState } from "react";
import { fetchOpsErrors, fetchOpsPositions, fetchOpsStatus, queueMinaCommand, sendOpsCommand } from "../api/ops";
import { queueUnifiedKillSwitch, type UnifiedRole } from "../api/unified";
import { fetchLiveRollout, fetchLiveSafetyPolicy, setLiveRollout, updateLiveSafetyPolicy } from "../api/live";
import { DataTable, KpiCard, Panel, SectionHeader, StatusBadge, TerminalBox, formatNum, toneFromValue } from "../components/mina";
import { clearLivePolicyCache, requestLiveGuard } from "../utils/liveGuard";

const ROLES = ["all", "paper", "live", "pump"] as const;
type RoleValue = (typeof ROLES)[number];

function roleTone(lastHeartbeat: string | null | undefined) {
  if (!lastHeartbeat) return "bad";
  const t = Date.parse(lastHeartbeat);
  if (!Number.isFinite(t)) return "warn";
  const seconds = (Date.now() - t) / 1000;
  if (seconds <= 20) return "good";
  if (seconds <= 90) return "warn";
  return "bad";
}

export default function OpsLive() {
  const [role, setRole] = useState<RoleValue>("live");
  const [status, setStatus] = useState<any>(null);
  const [positions, setPositions] = useState<any[]>([]);
  const [errors, setErrors] = useState<any[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [logFilter, setLogFilter] = useState("");
  const [logLevel, setLogLevel] = useState("ALL");
  const [logService, setLogService] = useState("");
  const [lastUpdated, setLastUpdated] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string>("");
  const [livePolicy, setLivePolicy] = useState<any>(null);
  const [liveRuntime, setLiveRuntime] = useState<any>(null);
  const [livePin, setLivePin] = useState("");
  const esRef = useRef<EventSource | null>(null);

  const loadLive = async () => {
    try {
      const [policy, rollout] = await Promise.all([fetchLiveSafetyPolicy(true), fetchLiveRollout()]);
      setLivePolicy(policy?.policy || rollout?.policy || null);
      setLiveRuntime(policy?.runtime || rollout?.runtime || null);
    } catch {
      setLivePolicy(null);
      setLiveRuntime(null);
    }
  };

  const load = async () => {
    try {
      const [s, p, e] = await Promise.all([fetchOpsStatus(role), fetchOpsPositions(role, 100), fetchOpsErrors(role, 100)]);
      setStatus(s);
      setPositions(p?.items || []);
      setErrors(e?.items || []);
      await loadLive();
      setLastUpdated(new Date().toISOString());
    } catch (err: any) {
      setMessage(err?.message || "Failed to load ops data");
    }
  };

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 2000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  useEffect(() => {
    if (esRef.current) {
      esRef.current.close();
    }
    const qs = new URLSearchParams({ role });
    if (logLevel !== "ALL") qs.set("level", logLevel);
    if (logFilter) qs.set("contains", logFilter);
    if (logService) qs.set("service", logService);

    const es = new EventSource(`/api/ops/logs/stream?${qs.toString()}`);
    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        setLogs((prev) => [...prev, payload].slice(-300));
      } catch {
        // no-op
      }
    };
    es.onerror = () => es.close();
    esRef.current = es;
    return () => es.close();
  }, [role, logFilter, logLevel, logService]);

  const resolveRole = (rowRole?: string): UnifiedRole | null => {
    if (role !== "all") return role as UnifiedRole;
    if (rowRole && ["paper", "live", "pump"].includes(rowRole)) return rowRole as UnifiedRole;
    const pick = window.prompt("Choose role: paper | live | pump", "paper") || "";
    if (!["paper", "live", "pump"].includes(pick.trim().toLowerCase())) {
      setMessage("Invalid role selected.");
      return null;
    }
    return pick.trim().toLowerCase() as UnifiedRole;
  };

  const guardForRole = async (resolved: UnifiedRole, action: string) => {
    if (resolved !== "live") return undefined;
    return (await requestLiveGuard(action)) || undefined;
  };

  const runControl = async (target: "bot" | "monitor" | "pump", action: "start" | "stop" | "restart" | "reload_config") => {
    const resolved = resolveRole();
    if (!resolved) return;
    const guard = await guardForRole(resolved, `${action} ${target}`);
    if (resolved === "live" && !guard) return;
    const reason = window.prompt("Reason", "ops_live_manual") || "ops_live_manual";
    setBusy(true);
    try {
      await sendOpsCommand({ role: resolved, target, action, reason, ...(guard || {}) });
      setMessage(`${action} ${target} queued for ${resolved}`);
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Command failed");
    } finally {
      setBusy(false);
    }
  };

  const setKillSwitch = async (enabled: boolean) => {
    const resolved = resolveRole();
    if (!resolved) return;
    const guard = await guardForRole(resolved, enabled ? "Enable kill switch" : "Disable kill switch");
    if (resolved === "live" && !guard) return;
    const reason = window.prompt("Reason", enabled ? "ops_live_enable_kill_switch" : "ops_live_disable_kill_switch") || "ops_live";
    setBusy(true);
    try {
      await queueUnifiedKillSwitch(resolved, enabled, reason, guard);
      setMessage(`Kill switch ${enabled ? "ENABLED" : "DISABLED"} for ${resolved}`);
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Kill switch action failed");
    } finally {
      setBusy(false);
    }
  };

  const closeTrade = async (trade: any) => {
    const resolved = resolveRole(trade.role);
    if (!resolved) return;
    const guard = await guardForRole(resolved, `Close trade ${trade.symbol || trade.id || ""}`);
    if (resolved === "live" && !guard) return;
    try {
      await queueMinaCommand(resolved, "CLOSE_TRADE", { trade_id: trade.id, symbol: trade.symbol, reason: "OPS_CLOSE" }, guard);
      setMessage(`Close queued for ${trade.symbol}`);
    } catch (err: any) {
      setMessage(err?.message || "Close trade failed");
    }
  };

  const reduceTrade = async (trade: any) => {
    const resolved = resolveRole(trade.role);
    if (!resolved) return;
    const guard = await guardForRole(resolved, `Reduce trade ${trade.symbol || trade.id || ""}`);
    if (resolved === "live" && !guard) return;
    const pct = window.prompt("Reduce %", "25");
    if (!pct) return;
    try {
      await queueMinaCommand(resolved, "REDUCE_POSITION", {
        trade_id: trade.id,
        symbol: trade.symbol,
        reduce_pct: Number(pct),
      }, guard);
      setMessage(`Reduce queued for ${trade.symbol}`);
    } catch (err: any) {
      setMessage(err?.message || "Reduce failed");
    }
  };

  const moveSLTP = async (trade: any) => {
    const resolved = resolveRole(trade.role);
    if (!resolved) return;
    const guard = await guardForRole(resolved, `Move SL/TP ${trade.symbol || trade.id || ""}`);
    if (resolved === "live" && !guard) return;
    const sl = window.prompt("New stop loss price", trade.stop_loss ?? "");
    const tpRaw = window.prompt(
      "Take profits (comma separated)",
      Array.isArray(trade.take_profits) ? trade.take_profits.join(",") : "",
    );
    if (!sl && !tpRaw) return;
    const takeProfits = (tpRaw || "")
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean)
      .map((x) => Number(x))
      .filter((x) => Number.isFinite(x));
    try {
      await queueMinaCommand(resolved, "UPDATE_SLTP", {
        trade_id: trade.id,
        symbol: trade.symbol,
        stop_loss: sl ? Number(sl) : undefined,
        take_profits: takeProfits.length > 0 ? takeProfits : undefined,
      }, guard);
      setMessage(`SL/TP update queued for ${trade.symbol}`);
    } catch (err: any) {
      setMessage(err?.message || "SL/TP update failed");
    }
  };

  const saveLivePolicy = async () => {
    const guard = await requestLiveGuard("Update live safety policy", true);
    if (!guard) return;
    setBusy(true);
    try {
      const out = await updateLiveSafetyPolicy({
        execution_enabled: Boolean(livePolicy?.execution_enabled),
        double_confirm_required: Boolean(livePolicy?.double_confirm_required ?? true),
        pin_enabled: Boolean(livePolicy?.pin_enabled),
        live_pin: livePin || undefined,
        max_daily_loss: Number(livePolicy?.max_daily_loss || 0),
        max_open_positions: Number(livePolicy?.max_open_positions || 0),
        max_leverage: Number(livePolicy?.max_leverage || 0),
        max_notional: Number(livePolicy?.max_notional || 0),
        cooldown_sec: Number(livePolicy?.cooldown_sec || 0),
        ...guard,
      });
      clearLivePolicyCache();
      setLivePin("");
      setLivePolicy(out?.policy || livePolicy);
      setLiveRuntime(out?.runtime || liveRuntime);
      setMessage("Live safety policy saved.");
    } catch (err: any) {
      setMessage(err?.message || "Failed to save live safety policy.");
    } finally {
      setBusy(false);
    }
  };

  const applyRollout = async (stage: "LIVE-0" | "LIVE-1" | "LIVE-2") => {
    const guard = await requestLiveGuard(`Switch rollout stage to ${stage}`, true);
    if (!guard) return;
    setBusy(true);
    try {
      const out = await setLiveRollout(stage, guard);
      clearLivePolicyCache();
      setLivePolicy(out?.policy || livePolicy);
      setLiveRuntime(out?.runtime || liveRuntime);
      setMessage(`Rollout set to ${stage}.`);
    } catch (err: any) {
      setMessage(err?.message || "Failed to update rollout stage.");
    } finally {
      setBusy(false);
    }
  };

  const monitorRows = useMemo(() => {
    return Object.entries(status?.roles || {}).map(([r, v]: any) => ({
      role: r,
      schema: v?.schema || `mina_${r}`,
      heartbeat: v?.last_heartbeat,
      killSwitch: v?.kill_switch,
      decision: v?.last_decision || "—",
      version: v?.version || "—",
      error: v?.last_error?.msg || "—",
      errorTs: v?.last_error?.ts || "—",
    }));
  }, [status]);

  const logRows = useMemo(() => {
    return logs.map((entry) => {
      const row = entry?.row ?? entry ?? {};
      return {
        level: String(row.level || row.lvl || row.severity || "INFO").toUpperCase(),
        message: String(row.message || row.msg || row.text || ""),
        source: String(row.source || row.service || row.logger || "—"),
        ts: String(row.timestamp || row.time || row.created_at || row.ts || "—"),
      };
    });
  }, [logs]);

  return (
    <div>
      <SectionHeader
        title="Operations Center"
        subtitle="Active positions, terminal logs, role health, and runtime controls."
        right={<span className="muted">Last updated: {lastUpdated || "—"}</span>}
      />

      <Panel
        title="Controls"
        subtitle="Everything routes through Gateway command queue."
        right={<button data-testid="ops-refresh" className="action-btn" onClick={() => void load()}>Refresh</button>}
      >
        <div className="filters-row" style={{ marginBottom: 10 }}>
          <select data-testid="ops-role" className="dark-select" value={role} onChange={(e) => setRole(e.target.value as RoleValue)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button data-testid="ops-restart-bot" className="action-btn primary" disabled={busy} onClick={() => void runControl("bot", "restart")}>
            Restart Bot
          </button>
          <button data-testid="ops-restart-monitor" className="action-btn" disabled={busy} onClick={() => void runControl("monitor", "restart")}>
            Restart Monitor
          </button>
          <button data-testid="ops-restart-pump" className="action-btn" disabled={busy} onClick={() => void runControl("pump", "restart")}>
            Restart Pump
          </button>
          <button data-testid="ops-kill-on" className="action-btn bad" disabled={busy} onClick={() => void setKillSwitch(true)}>
            Kill Switch ON
          </button>
          <button data-testid="ops-kill-off" className="action-btn good" disabled={busy} onClick={() => void setKillSwitch(false)}>
            Kill Switch OFF
          </button>
          {message ? <span className="muted">{message}</span> : null}
        </div>
      </Panel>

      {(role === "live" || role === "all") ? (
        <Panel title="Live Safety Policy" subtitle="Live execution is OFF by default. Use rollout stages and hard caps for production readiness.">
          <div className="filters-row">
            <StatusBadge text={`Execution ${livePolicy?.execution_enabled ? "ON" : "OFF"}`} tone={livePolicy?.execution_enabled ? "warn" : "good"} />
            <StatusBadge text={`Rollout ${livePolicy?.rollout_stage || "LIVE-0"}`} tone="info" />
            <StatusBadge text={`Kill Switch ${liveRuntime?.kill_switch?.enabled ? "ON" : "OFF"}`} tone={liveRuntime?.kill_switch?.enabled ? "bad" : "good"} />
            <StatusBadge text={`Open Positions ${liveRuntime?.open_positions ?? 0}`} tone="neutral" />
            <StatusBadge text={`Daily PnL ${formatNum(liveRuntime?.daily_realized_pnl ?? 0)}`} tone={toneFromValue(liveRuntime?.daily_realized_pnl ?? 0)} />
          </div>
          <div className="grid-2" style={{ marginTop: 10 }}>
            <label className="muted">
              <input
                data-testid="live-policy-execution-enabled"
                type="checkbox"
                checked={Boolean(livePolicy?.execution_enabled)}
                onChange={(e) => setLivePolicy((p: any) => ({ ...(p || {}), execution_enabled: e.target.checked }))}
              />{" "}
              Live execution enabled
            </label>
            <label className="muted">
              <input
                data-testid="live-policy-double-confirm"
                type="checkbox"
                checked={Boolean(livePolicy?.double_confirm_required ?? true)}
                onChange={(e) => setLivePolicy((p: any) => ({ ...(p || {}), double_confirm_required: e.target.checked }))}
              />{" "}
              Require double-confirm
            </label>
            <label className="muted">
              <input
                data-testid="live-policy-pin-enabled"
                type="checkbox"
                checked={Boolean(livePolicy?.pin_enabled)}
                onChange={(e) => setLivePolicy((p: any) => ({ ...(p || {}), pin_enabled: e.target.checked }))}
              />{" "}
              Require PIN
            </label>
            <label className="muted">
              Set/Rotate PIN (optional)
              <input data-testid="live-policy-pin" className="dark-input" type="password" value={livePin} onChange={(e) => setLivePin(e.target.value)} />
            </label>
            <label className="muted">
              Max Daily Loss (USDT)
              <input
                data-testid="live-policy-max-daily-loss"
                className="dark-input"
                value={String(livePolicy?.max_daily_loss ?? 0)}
                onChange={(e) => setLivePolicy((p: any) => ({ ...(p || {}), max_daily_loss: Number(e.target.value || 0) }))}
              />
            </label>
            <label className="muted">
              Max Open Positions
              <input
                data-testid="live-policy-max-open-positions"
                className="dark-input"
                value={String(livePolicy?.max_open_positions ?? 1)}
                onChange={(e) => setLivePolicy((p: any) => ({ ...(p || {}), max_open_positions: Number(e.target.value || 0) }))}
              />
            </label>
            <label className="muted">
              Max Leverage
              <input
                data-testid="live-policy-max-leverage"
                className="dark-input"
                value={String(livePolicy?.max_leverage ?? 0)}
                onChange={(e) => setLivePolicy((p: any) => ({ ...(p || {}), max_leverage: Number(e.target.value || 0) }))}
              />
            </label>
            <label className="muted">
              Max Notional (USDT)
              <input
                data-testid="live-policy-max-notional"
                className="dark-input"
                value={String(livePolicy?.max_notional ?? 0)}
                onChange={(e) => setLivePolicy((p: any) => ({ ...(p || {}), max_notional: Number(e.target.value || 0) }))}
              />
            </label>
            <label className="muted">
              Cooldown (sec)
              <input
                data-testid="live-policy-cooldown"
                className="dark-input"
                value={String(livePolicy?.cooldown_sec ?? 0)}
                onChange={(e) => setLivePolicy((p: any) => ({ ...(p || {}), cooldown_sec: Number(e.target.value || 0) }))}
              />
            </label>
          </div>
          <div className="filters-row" style={{ marginTop: 10 }}>
            <button data-testid="live-policy-save" className="action-btn primary" disabled={busy} onClick={() => void saveLivePolicy()}>
              Save Live Policy
            </button>
            <button data-testid="live-rollout-0" className="action-btn" disabled={busy} onClick={() => void applyRollout("LIVE-0")}>
              LIVE-0 Shadow
            </button>
            <button data-testid="live-rollout-1" className="action-btn warn" disabled={busy} onClick={() => void applyRollout("LIVE-1")}>
              LIVE-1 Small Capital
            </button>
            <button data-testid="live-rollout-2" className="action-btn bad" disabled={busy} onClick={() => void applyRollout("LIVE-2")}>
              LIVE-2 Gradual
            </button>
          </div>
        </Panel>
      ) : null}

      <Panel title="Runtime Snapshot">
        <div className="kpi-grid">
          <KpiCard label="Open Positions" value={positions.length} />
          <KpiCard label="Recent Errors" value={errors.length} tone={errors.length > 0 ? "warn" : "good"} />
          <KpiCard label="Terminal Lines" value={logs.length} />
          <KpiCard
            label="Active Roles"
            value={monitorRows.filter((r) => roleTone(r.heartbeat) === "good").length}
            hint={`${monitorRows.length} roles tracked`}
          />
        </div>
      </Panel>

      <Panel title="Live Monitor">
        <DataTable
          rows={monitorRows}
          emptyText="No monitor data yet."
          columns={[
            { key: "role", title: "Role", render: (row) => row.role },
            { key: "schema", title: "Schema", render: (row) => row.schema },
            {
              key: "hb",
              title: "Heartbeat",
              render: (row) => <StatusBadge text={row.heartbeat || "missing"} tone={roleTone(row.heartbeat)} />,
            },
            {
              key: "kill",
              title: "Kill Switch",
              render: (row) => <StatusBadge text={String(row.killSwitch || "0")} tone={String(row.killSwitch) === "1" ? "bad" : "good"} />,
            },
            { key: "decision", title: "Last Decision", render: (row) => row.decision || "—" },
            { key: "version", title: "Version", render: (row) => row.version },
            { key: "error", title: "Last Error", render: (row) => row.error || "—" },
          ]}
        />
      </Panel>

      <Panel title="Active Positions" subtitle="Close / Reduce / Move SLTP from one place.">
        <DataTable
          rows={positions}
          emptyText="No active positions."
          columns={[
            { key: "role", title: "Role", render: (row: any) => row.role || role },
            { key: "symbol", title: "Symbol", render: (row: any) => row.symbol || row.pair || "—" },
            { key: "status", title: "Status", render: (row: any) => row.status || "—" },
            { key: "size", title: "Size", render: (row: any) => formatNum(row.qty || row.size || row.position_amt) },
            { key: "entry", title: "Entry", render: (row: any) => formatNum(row.entry_price || row.entry) },
            { key: "mark", title: "Mark", render: (row: any) => formatNum(row.mark_price || row.mark) },
            {
              key: "pnl",
              title: "PnL",
              render: (row: any) => <StatusBadge text={formatNum(row.pnl || row.unrealized_pnl)} tone={toneFromValue(row.pnl || row.unrealized_pnl)} />,
            },
            { key: "opened", title: "Opened", render: (row: any) => row.opened_at || row.created_at || "—" },
            {
              key: "actions",
              title: "Actions",
              render: (row: any) => (
                <div className="filters-row">
                  <button className="action-btn bad" onClick={() => void closeTrade(row)}>Close</button>
                  <button className="action-btn" onClick={() => void reduceTrade(row)}>Reduce</button>
                  <button className="action-btn" onClick={() => void moveSLTP(row)}>Move SL/TP</button>
                </div>
              ),
            },
          ]}
        />
      </Panel>

      <Panel
        title="Live Terminal"
        subtitle="SSE stream from /api/ops/logs/stream"
        right={
          <div className="filters-row">
            <input className="dark-input" placeholder="contains…" value={logFilter} onChange={(e) => setLogFilter(e.target.value)} />
            <input className="dark-input" placeholder="service…" value={logService} onChange={(e) => setLogService(e.target.value)} />
            <select className="dark-select" value={logLevel} onChange={(e) => setLogLevel(e.target.value)}>
              {["ALL", "INFO", "WARN", "ERROR", "SYSTEM", "TRADE"].map((lvl) => (
                <option key={lvl} value={lvl}>
                  {lvl}
                </option>
              ))}
            </select>
          </div>
        }
      >
        <TerminalBox lines={logRows} maxHeight={360} />
      </Panel>

      <Panel title="Errors Detected" subtitle="Latest ERROR logs across selected roles.">
        <DataTable
          rows={errors}
          emptyText="No errors."
          columns={[
            { key: "role", title: "Role", render: (row: any) => row.role || "—" },
            {
              key: "level",
              title: "Level",
              render: (row: any) => <StatusBadge text={String(row.level || row.lvl || "ERROR")} tone="bad" />,
            },
            { key: "source", title: "Source", render: (row: any) => row.source || row.service || "—" },
            { key: "message", title: "Message", render: (row: any) => row.message || row.msg || "—" },
            { key: "ts", title: "Time", render: (row: any) => row.timestamp || row.time || row.created_at || "—" },
          ]}
        />
      </Panel>
    </div>
  );
}
