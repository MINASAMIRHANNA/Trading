import { useEffect, useMemo, useState } from "react";
import { clearOldCommands, clearRestartFlags, fetchDoctorChecks, fetchDoctorIncidents, fetchDoctorStatus, runDoctor } from "../api/doctor";
import { DataTable, KpiCard, Panel, SectionHeader, StatusPill } from "../components/mina";

const ROLES = ["all", "paper", "live", "pump"] as const;

function severityTone(sev: string) {
  const s = String(sev || "").toUpperCase();
  if (s === "OK") return "good";
  if (s === "WARN") return "warn";
  if (s === "CRIT" || s === "ERROR") return "bad";
  return "neutral";
}

export default function ProjectDoctor() {
  const [role, setRole] = useState<(typeof ROLES)[number]>("all");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  const [checks, setChecks] = useState<any[]>([]);
  const [incidents, setIncidents] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>({ total: 0, ok: 0, warn: 0, crit: 0 });
  const [legacyStatus, setLegacyStatus] = useState<any>(null);

  const loadStatus = async () => {
    try {
      setLegacyStatus(await fetchDoctorStatus());
    } catch {
      setLegacyStatus(null);
    }
  };

  const loadChecks = async (runTests: boolean) => {
    setLoading(true);
    try {
      const out = await fetchDoctorChecks(runTests);
      const rows = Array.isArray(out?.checks) ? out.checks : [];
      setChecks(rows);
      setSummary(out?.summary || { total: rows.length, ok: 0, warn: 0, crit: 0 });
      setMessage(runTests ? "Doctor checks completed (including write/event tests)." : "Doctor checks completed.");
    } catch (err: any) {
      setMessage(err?.message || "Failed to run doctor checks.");
    } finally {
      setLoading(false);
    }
  };

  const loadIncidents = async () => {
    try {
      const out = await fetchDoctorIncidents(50);
      setIncidents(Array.isArray(out?.items) ? out.items : []);
    } catch {
      setIncidents([]);
    }
  };

  useEffect(() => {
    void loadStatus();
    void loadChecks(true);
    void loadIncidents();
  }, []);

  const runLegacyDoctor = async () => {
    setLoading(true);
    try {
      await runDoctor();
      setMessage("Legacy doctor run completed.");
      await loadStatus();
    } catch (err: any) {
      setMessage(err?.message || "Legacy doctor run failed.");
    } finally {
      setLoading(false);
    }
  };

  const runClearRestart = async () => {
    try {
      await clearRestartFlags(role);
      setMessage(`Restart flags cleared for ${role}.`);
      await loadChecks(false);
      await loadIncidents();
    } catch (err: any) {
      setMessage(err?.message || "Failed to clear restart flags.");
    }
  };

  const runClearCommands = async () => {
    const ageMinRaw = window.prompt("Age minutes", "30") || "30";
    const ageMin = Number.isFinite(Number(ageMinRaw)) ? Number(ageMinRaw) : 30;
    try {
      const out = await clearOldCommands(role, ageMin);
      setMessage(`Cleared ${out?.cleared || 0} stale commands.`);
      await loadChecks(false);
      await loadIncidents();
    } catch (err: any) {
      setMessage(err?.message || "Failed to clear commands.");
    }
  };

  const wiring = legacyStatus?.dbWiring || {};
  const registryRows = Array.isArray(wiring?.service_registry) ? wiring.service_registry : [];

  const specialRows = useMemo(() => {
    const index: Record<string, any> = {};
    for (const row of checks) {
      if (row?.name) index[String(row.name)] = row;
    }
    return [
      index.write_path_test,
      index.event_ingestion_test,
      index.brain_sync_lag,
      index.queue_health,
      index.db_connectivity,
    ].filter(Boolean);
  }, [checks]);

  return (
    <div>
      <SectionHeader
        title="Project Doctor"
        subtitle="Connectivity + schema + heartbeat + queue + sync-lag diagnostics with write/event path tests."
        right={message ? <span className="muted">{message}</span> : null}
      />

      <Panel title="Summary">
        <div className="kpi-grid">
          <KpiCard label="Checks" value={summary?.total || checks.length || 0} />
          <KpiCard label="OK" value={summary?.ok || 0} tone="good" />
          <KpiCard label="WARN" value={summary?.warn || 0} tone="warn" />
          <KpiCard label="CRIT" value={summary?.crit || 0} tone="bad" />
          <KpiCard label="Single DB" value={wiring?.same_db ? "YES" : "NO"} tone={wiring?.same_db ? "good" : "bad"} />
          <KpiCard label="Service Registry" value={registryRows.length} tone={registryRows.length > 0 ? "good" : "warn"} />
        </div>
      </Panel>

      <Panel title="Actions">
        <div className="filters-row">
          <select className="dark-select" value={role} onChange={(e) => setRole(e.target.value as any)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button className="action-btn primary" disabled={loading} onClick={() => void loadChecks(true)}>
            Run Full Checks
          </button>
          <button className="action-btn" disabled={loading} onClick={() => void loadChecks(false)}>
            Quick Checks
          </button>
          <button className="action-btn" disabled={loading} onClick={() => void loadStatus()}>
            Refresh DB Wiring
          </button>
          <button className="action-btn" disabled={loading} onClick={() => void loadIncidents()}>
            Refresh Incidents
          </button>
          <button className="action-btn" disabled={loading} onClick={() => void runLegacyDoctor()}>
            Legacy Doctor Run
          </button>
          <button className="action-btn bad" disabled={loading} onClick={() => void runClearRestart()}>
            Clear Restart Flags
          </button>
          <button className="action-btn warn" disabled={loading} onClick={() => void runClearCommands()}>
            Clear Old Commands
          </button>
        </div>
      </Panel>

      <div className="grid-2">
        <Panel title="Recommended Checks">
          <DataTable
            rows={specialRows}
            emptyText="No recommended check rows yet."
            columns={[
              { key: "name", title: "Check", render: (row: any) => row.name || "—" },
              {
                key: "severity",
                title: "Severity",
                render: (row: any) => <StatusPill text={row.severity || "—"} tone={severityTone(row.severity || "")} />,
              },
              { key: "details", title: "Details", render: (row: any) => row.details || "—" },
            ]}
          />
        </Panel>

        <Panel title="DB Service Registry">
          <DataTable
            rows={registryRows}
            emptyText="No service registry rows found."
            columns={[
              { key: "service_name", title: "Service", render: (row: any) => row.service_name || "—" },
              { key: "role", title: "Role", render: (row: any) => row.role || "—" },
              { key: "schema_name", title: "Schema", render: (row: any) => row.schema_name || "—" },
              { key: "db_name", title: "DB", render: (row: any) => row.db_name || "—" },
              { key: "db_host", title: "Host", render: (row: any) => row.db_host || "—" },
              { key: "started_at", title: "Started", render: (row: any) => row.started_at || "—" },
            ]}
          />
        </Panel>
      </div>

      <Panel title="All Doctor Checks">
        <DataTable
          rows={checks}
          emptyText="No checks yet."
          columns={[
            { key: "name", title: "Check", render: (row: any) => row.name || "—" },
            {
              key: "severity",
              title: "Severity",
              render: (row: any) => <StatusPill text={row.severity || "—"} tone={severityTone(row.severity || "")} />,
            },
            { key: "details", title: "Details", render: (row: any) => row.details || "—" },
            {
              key: "data",
              title: "Data",
              render: (row: any) => {
                if (row.data === undefined || row.data === null) return "—";
                return <code>{typeof row.data === "object" ? JSON.stringify(row.data) : String(row.data)}</code>;
              },
            },
          ]}
        />
      </Panel>

      <Panel title="Incident View" subtitle="Last 50 errors/incidents with suggested fix and trace id.">
        <DataTable
          rows={incidents}
          emptyText="No incidents recorded."
          enableCopy
          columns={[
            { key: "ts_utc", title: "Time", render: (row: any) => row.ts_utc || "—" },
            { key: "role", title: "Role", render: (row: any) => row.role || "—" },
            {
              key: "severity",
              title: "Severity",
              render: (row: any) => <StatusPill text={row.severity || "WARN"} tone={severityTone(row.severity || "WARN")} />,
            },
            { key: "message", title: "Message", render: (row: any) => row.message || "—" },
            { key: "suggested_fix", title: "Suggested Fix", render: (row: any) => row.suggested_fix || "—" },
            {
              key: "trace_id",
              title: "Trace",
              render: (row: any) => (
                <button
                  className="mini-btn"
                  onClick={() => {
                    const t = String(row.trace_id || "");
                    if (!t) return;
                    void navigator.clipboard.writeText(t);
                  }}
                >
                  {row.trace_id ? "Copy trace_id" : "—"}
                </button>
              ),
            },
          ]}
        />
      </Panel>
    </div>
  );
}
