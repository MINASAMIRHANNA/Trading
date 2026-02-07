import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { fetchMinaStatus } from "../api/minaPages";
import { sendOpsCommand } from "../api/ops";
import { type UnifiedRole, fetchUnifiedSystemHealth, queueUnifiedKillSwitch } from "../api/unified";
import { DataTable, KpiCard, Panel, SectionHeader, StatusPill } from "../components/mina";
import ProjectDoctor from "./ProjectDoctor";
import { requestLiveGuard } from "../utils/liveGuard";

type TabKey = "status" | "doctor";

export default function StatusMaintenance() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [tab, setTab] = useState<TabKey>("status");
  const [message, setMessage] = useState("");
  const [lastUpdated, setLastUpdated] = useState("");
  const [busy, setBusy] = useState(false);

  const [stack, setStack] = useState<any>(null);
  const [statusByRole, setStatusByRole] = useState<Record<string, any>>({});
  const [healthByRole, setHealthByRole] = useState<Record<string, any>>({});
  const [runtimeByRole, setRuntimeByRole] = useState<Record<string, any>>({});
  const [dbFingerprint, setDbFingerprint] = useState<any>(null);

  const load = async () => {
    try {
      const [stackRes, pStatus, lStatus, uStatus, pHealth, lHealth, uHealth, runtimeRes, dbRes] = await Promise.all([
        api.get("/stack/health"),
        fetchMinaStatus("paper"),
        fetchMinaStatus("live"),
        fetchMinaStatus("pump"),
        fetchUnifiedSystemHealth("paper"),
        fetchUnifiedSystemHealth("live"),
        fetchUnifiedSystemHealth("pump"),
        api.get("/ops/runtime?role=all"),
        api.get("/ops/db_fingerprint"),
      ]);
      setStack(stackRes?.data || {});
      setStatusByRole({ paper: pStatus, live: lStatus, pump: uStatus });
      setHealthByRole({ paper: pHealth, live: lHealth, pump: uHealth });
      setRuntimeByRole(runtimeRes?.data?.items || {});
      setDbFingerprint(dbRes?.data || {});
      setLastUpdated(new Date().toISOString());
      setMessage("");
    } catch (err: any) {
      setMessage(err?.message || "Failed to load status.");
    }
  };

  useEffect(() => {
    if (tab !== "status") return;
    void load();
    const id = setInterval(() => void load(), 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const runMaintenance = async (target: "bot" | "monitor" | "pump", action: "restart" | "stop" | "start") => {
    const guard = role === "live" ? await requestLiveGuard(`${action} ${target}`) : null;
    if (role === "live" && !guard) return;
    setBusy(true);
    try {
      await sendOpsCommand({ role, target, action, reason: "status_maintenance", ...(guard || {}) });
      setMessage(`${action} ${target} queued for ${role}.`);
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Maintenance action failed.");
    } finally {
      setBusy(false);
    }
  };

  const setKillSwitch = async (enabled: boolean) => {
    if (role !== "paper") {
      setMessage("Kill switch controls in this view are limited to TEST/PAPER role.");
      return;
    }
    setBusy(true);
    try {
      await queueUnifiedKillSwitch(role, enabled, "status_maintenance");
      setMessage(`Kill switch ${enabled ? "ENABLED" : "DISABLED"} for ${role}.`);
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Kill switch action failed.");
    } finally {
      setBusy(false);
    }
  };

  const stackRows = useMemo(() => {
    const out: Array<{ component: string; status: string; details: string }> = [];
    const s = stack || {};
    for (const [k, v] of Object.entries(s || {})) {
      out.push({
        component: k,
        status: typeof v === "object" ? String((v as any).status || (v as any).ok || "unknown") : String(v),
        details: typeof v === "object" ? JSON.stringify(v) : String(v),
      });
    }
    return out;
  }, [stack]);

  const dashboardRows = useMemo(() => {
    const rows: any[] = [];
    for (const r of ["paper", "live", "pump"]) {
      const st = statusByRole[r] || {};
      const h = healthByRole[r] || {};
      rows.push({
        role: r,
        online: Boolean(h?.online),
        kill_switch: String(h?.kill_switch || st?.kill_switch || "0"),
        heartbeat: h?.last_seen_seconds ?? "—",
        last_decision: st?.last_decision || "—",
        last_error: st?.last_error || h?.last_error || "—",
        link: r === "paper" ? "http://localhost:8000" : r === "live" ? "http://localhost:8001" : "http://localhost:8002",
      });
    }
    return rows;
  }, [healthByRole, statusByRole]);

  const kpis = useMemo(() => {
    const onlineCount = dashboardRows.filter((x) => x.online).length;
    return [
      { label: "Role Scope", value: role },
      { label: "Dashboards Online", value: `${onlineCount}/3`, tone: onlineCount === 3 ? "good" : "warn" },
      { label: "Stack Keys", value: stackRows.length },
      { label: "Last Updated", value: lastUpdated || "—" },
    ];
  }, [dashboardRows, lastUpdated, role, stackRows.length]);

  const runtimeRows = useMemo(() => {
    return Object.entries(runtimeByRole || {}).map(([r, v]) => ({ role: r, ...(v as any) }));
  }, [runtimeByRole]);

  const pumpRuntime = runtimeByRole?.pump || {};
  const pumpEntrypointOk = String(pumpRuntime?.entrypoint || "").includes("pump_hunter.py");
  const dbHost = String(dbFingerprint?.dsn?.host || "");
  const dbName = String(dbFingerprint?.dsn?.db || "");
  const singleDbOk = dbHost === "postgres" && dbName === "trading";

  return (
    <div>
      <SectionHeader
        title="Status (System Status & Maintenance)"
        subtitle="Global stack health, maintenance actions, and legacy dashboard display-only status."
        right={message ? <span className="muted">{message}</span> : null}
      />

      <Panel title="Scope">
        <div className="filters-row">
          <select data-testid="status-role" className="dark-select" value={role} onChange={(e) => setRole(e.target.value as UnifiedRole)}>
            <option value="paper">paper</option>
            <option value="live">live</option>
            <option value="pump">pump</option>
          </select>
          <button data-testid="status-tab-status" className={`action-btn${tab === "status" ? " primary" : ""}`} onClick={() => setTab("status")}>
            Status
          </button>
          <button data-testid="status-tab-doctor" className={`action-btn${tab === "doctor" ? " primary" : ""}`} onClick={() => setTab("doctor")}>
            Doctor
          </button>
          <button data-testid="status-refresh" className="action-btn" onClick={() => void load()}>
            Refresh
          </button>
          {role === "live" ? <StatusPill text="LIVE role selected" tone="warn" /> : null}
        </div>
      </Panel>

      {tab === "status" ? (
        <>
          <Panel title="Snapshot">
            <div className="kpi-grid">
              {kpis.map((k) => (
                <KpiCard key={k.label} label={k.label} value={k.value} tone={(k as any).tone || "neutral"} />
              ))}
            </div>
          </Panel>

          <Panel title="Maintenance Actions" subtitle="Actions are queued through /api/ops/command.">
            <div className="filters-row">
              <button data-testid="status-restart-bot" className="action-btn primary" disabled={busy} onClick={() => void runMaintenance("bot", "restart")}>Restart Bot</button>
              <button data-testid="status-restart-monitor" className="action-btn" disabled={busy} onClick={() => void runMaintenance("monitor", "restart")}>Restart Monitor</button>
              <button data-testid="status-restart-pump" className="action-btn" disabled={busy} onClick={() => void runMaintenance("pump", "restart")}>Restart Pump</button>
              <button data-testid="status-stop-bot" className="action-btn warn" disabled={busy} onClick={() => void runMaintenance("bot", "stop")}>Stop Bot</button>
              <button data-testid="status-start-bot" className="action-btn good" disabled={busy} onClick={() => void runMaintenance("bot", "start")}>Start Bot</button>
              <button
                data-testid="status-kill-on"
                className="action-btn bad"
                disabled={busy || role !== "paper"}
                onClick={() => void setKillSwitch(true)}
              >
                Kill Switch ON (paper)
              </button>
              <button
                data-testid="status-kill-off"
                className="action-btn good"
                disabled={busy || role !== "paper"}
                onClick={() => void setKillSwitch(false)}
              >
                Kill Switch OFF (paper)
              </button>
            </div>
          </Panel>

          <div className="grid-2">
            <Panel title="Global Stack Status">
              <DataTable
                rows={stackRows}
                emptyText="No stack data."
                columns={[
                  { key: "component", title: "Component", render: (row: any) => row.component },
                  {
                    key: "status",
                    title: "Status",
                    render: (row: any) => <StatusPill text={row.status} tone={String(row.status).toLowerCase().includes("ok") ? "good" : "warn"} />,
                  },
                  { key: "details", title: "Details", render: (row: any) => row.details },
                ]}
              />
            </Panel>

            <Panel title="Legacy Dashboards (Display-Only)">
              <DataTable
                rows={dashboardRows}
                emptyText="No dashboard status."
                columns={[
                  { key: "role", title: "Role", render: (row: any) => row.role },
                  {
                    key: "online",
                    title: "Online",
                    render: (row: any) => <StatusPill text={row.online ? "ONLINE" : "OFFLINE"} tone={row.online ? "good" : "bad"} />,
                  },
                  {
                    key: "kill_switch",
                    title: "Kill Switch",
                    render: (row: any) => <StatusPill text={row.kill_switch === "1" ? "ON" : "OFF"} tone={row.kill_switch === "1" ? "bad" : "good"} />,
                  },
                  { key: "heartbeat", title: "Last Seen (s)", render: (row: any) => String(row.heartbeat) },
                  { key: "last_decision", title: "Last Decision", render: (row: any) => row.last_decision },
                  {
                    key: "link",
                    title: "Link",
                    render: (row: any) => (
                      <a href={row.link} target="_blank" rel="noreferrer" className="nav-item" style={{ padding: "4px 8px" }}>
                        {row.link}
                      </a>
                    ),
                  },
                ]}
              />
            </Panel>
          </div>

          <div className="grid-2">
            <Panel title="Runtime Assertions">
              <div className="kpi-grid">
                <KpiCard label="Pump Entrypoint" value={pumpRuntime?.entrypoint || "—"} tone={pumpEntrypointOk ? "good" : "bad"} />
                <KpiCard label="Pump Heartbeat (s)" value={pumpRuntime?.last_seen_seconds ?? "—"} tone={pumpRuntime?.online ? "good" : "warn"} />
                <KpiCard label="Single DB Host" value={dbHost || "—"} tone={singleDbOk ? "good" : "warn"} />
                <KpiCard label="Single DB Name" value={dbName || "—"} tone={singleDbOk ? "good" : "warn"} />
              </div>
              <div className="filters-row" style={{ marginTop: 10 }}>
                <StatusPill text={pumpEntrypointOk ? "pump_hunter.py confirmed" : "pump entrypoint mismatch"} tone={pumpEntrypointOk ? "good" : "bad"} />
                <StatusPill text={singleDbOk ? "single TRADING_PG_DSN confirmed" : "check DB fingerprint"} tone={singleDbOk ? "good" : "warn"} />
              </div>
            </Panel>

            <Panel title="Runtime by Role">
              <DataTable
                rows={runtimeRows}
                emptyText="No runtime rows."
                columns={[
                  { key: "role", title: "Role", render: (row: any) => row.role },
                  { key: "service_name", title: "Service", render: (row: any) => row.service_name || "—" },
                  { key: "entrypoint", title: "Entrypoint", render: (row: any) => row.entrypoint || "—" },
                  { key: "online", title: "Online", render: (row: any) => <StatusPill text={row.online ? "ONLINE" : "OFFLINE"} tone={row.online ? "good" : "bad"} /> },
                  { key: "last_seen_seconds", title: "Last Seen (s)", render: (row: any) => String(row.last_seen_seconds ?? "—") },
                  { key: "last_error", title: "Last Error", render: (row: any) => row.last_error || "—" },
                ]}
              />
            </Panel>
          </div>

          <Panel title="Runbook Shortcuts">
            <pre className="code-block">bash scripts/smoke_stack.sh{"\n"}bash scripts/smoke_unified_pages.sh{"\n"}bash scripts/smoke_e2e_trade.sh{"\n"}bash scripts/smoke_ui_e2e.sh</pre>
          </Panel>
        </>
      ) : (
        <ProjectDoctor />
      )}
    </div>
  );
}
