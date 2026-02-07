import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { fetchMinaStatus } from "../api/minaPages";
import { sendOpsCommand } from "../api/ops";
import { type UnifiedRole, fetchUnifiedSystemHealth } from "../api/unified";
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

  const load = async () => {
    try {
      const [stackRes, pStatus, lStatus, uStatus, pHealth, lHealth, uHealth] = await Promise.all([
        api.get("/stack/health"),
        fetchMinaStatus("paper"),
        fetchMinaStatus("live"),
        fetchMinaStatus("pump"),
        fetchUnifiedSystemHealth("paper"),
        fetchUnifiedSystemHealth("live"),
        fetchUnifiedSystemHealth("pump"),
      ]);
      setStack(stackRes?.data || {});
      setStatusByRole({ paper: pStatus, live: lStatus, pump: uStatus });
      setHealthByRole({ paper: pHealth, live: lHealth, pump: uHealth });
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

  return (
    <div>
      <SectionHeader
        title="Status (System Status & Maintenance)"
        subtitle="Global stack health, maintenance actions, and legacy dashboard display-only status."
        right={message ? <span className="muted">{message}</span> : null}
      />

      <Panel title="Scope">
        <div className="filters-row">
          <select className="dark-select" value={role} onChange={(e) => setRole(e.target.value as UnifiedRole)}>
            <option value="paper">paper</option>
            <option value="live">live</option>
            <option value="pump">pump</option>
          </select>
          <button className={`action-btn${tab === "status" ? " primary" : ""}`} onClick={() => setTab("status")}>
            Status
          </button>
          <button className={`action-btn${tab === "doctor" ? " primary" : ""}`} onClick={() => setTab("doctor")}>
            Doctor
          </button>
          <button className="action-btn" onClick={() => void load()}>
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
              <button className="action-btn primary" disabled={busy} onClick={() => void runMaintenance("bot", "restart")}>Restart Bot</button>
              <button className="action-btn" disabled={busy} onClick={() => void runMaintenance("monitor", "restart")}>Restart Monitor</button>
              <button className="action-btn" disabled={busy} onClick={() => void runMaintenance("pump", "restart")}>Restart Pump</button>
              <button className="action-btn warn" disabled={busy} onClick={() => void runMaintenance("bot", "stop")}>Stop Bot</button>
              <button className="action-btn good" disabled={busy} onClick={() => void runMaintenance("bot", "start")}>Start Bot</button>
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
        </>
      ) : (
        <ProjectDoctor />
      )}
    </div>
  );
}
