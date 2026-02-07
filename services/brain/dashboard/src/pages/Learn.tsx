import { useEffect, useMemo, useState } from "react";
import {
  fetchLearnConfig,
  fetchLearnKpis,
  fetchLearnState,
  fetchLearnStatus,
  promoteLearnCandidate,
  rollbackLearnDeployed,
  triggerLearnTrainForRole,
  updateLearnConfig,
} from "../api/learn";
import { DataTable, Panel, SectionHeader, StatusPill } from "../components/mina";
import { requestLiveGuard } from "../utils/liveGuard";

const ROLES = ["paper", "live", "pump"] as const;
type Role = (typeof ROLES)[number];

export default function Learn() {
  const [role, setRole] = useState<Role>("paper");
  const [state, setState] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [config, setConfig] = useState<any>({});
  const [kpis, setKpis] = useState<any>({});
  const [windowDays, setWindowDays] = useState<number>(30);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = async () => {
    try {
      const [st, ss, cfg, k] = await Promise.all([fetchLearnState(), fetchLearnStatus(), fetchLearnConfig(), fetchLearnKpis({ role: "all" })]);
      setState(st?.state || st || {});
      setStatus(ss || {});
      const mergedCfg = cfg?.config || st?.config || {};
      setConfig(mergedCfg);
      setWindowDays(Number(mergedCfg?.window_days || 30));
      setKpis(k?.items || st?.kpis || {});
      setMessage("");
    } catch (err: any) {
      setMessage(err?.message || "Failed to load learn state.");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const runTrain = async () => {
    const guard = role === "live" ? await requestLiveGuard("Run training") : null;
    if (role === "live" && !guard) return;
    setBusy(true);
    try {
      const out = await triggerLearnTrainForRole(role, {
        window_days: windowDays,
        label_rule: config?.label_rule,
        calibration: config?.calibration,
        veto_filters: config?.veto_filters,
        dynamic_thresholds: config?.dynamic_thresholds,
        ...(guard || {}),
      });
      setMessage(`Training started for ${role}. candidate=${out?.candidate_version || "n/a"}`);
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Train failed.");
    } finally {
      setBusy(false);
    }
  };

  const runPromote = async () => {
    const guard = role === "live" ? await requestLiveGuard("Promote candidate model") : null;
    if (role === "live" && !guard) return;
    setBusy(true);
    try {
      const out = await promoteLearnCandidate(role, undefined, guard || {});
      setMessage(`Promoted ${role} -> ${out?.deployed_version || "n/a"}`);
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Promote failed.");
    } finally {
      setBusy(false);
    }
  };

  const runRollback = async () => {
    const guard = role === "live" ? await requestLiveGuard("Rollback deployed model") : null;
    if (role === "live" && !guard) return;
    setBusy(true);
    try {
      const out = await rollbackLearnDeployed(role, guard || {});
      setMessage(`Rolled back ${role} -> ${out?.deployed_version || "n/a"}`);
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Rollback failed.");
    } finally {
      setBusy(false);
    }
  };

  const saveConfig = async () => {
    setBusy(true);
    try {
      await updateLearnConfig({
        ...config,
        window_days: Number(windowDays || 30),
      });
      setMessage("Learning config updated.");
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Failed to update learning config.");
    } finally {
      setBusy(false);
    }
  };

  const deployed = state?.deployed_model_versions || {};
  const previous = state?.previous_deployed_versions || {};
  const candidate = state?.candidate_model_versions || {};
  const thresholds = state?.thresholds || {};

  const modelRows = useMemo(
    () =>
      ROLES.map((r) => ({
        role: r,
        deployed: deployed?.[r] || "—",
        candidate: candidate?.[r] || "—",
        previous: previous?.[r] || "—",
      })),
    [candidate, deployed, previous],
  );

  const thresholdRows = useMemo(
    () => Object.entries(thresholds || {}).map(([k, v]) => ({ regime: k, value: typeof v === "object" ? JSON.stringify(v) : String(v) })),
    [thresholds],
  );

  const kpiRows = useMemo(
    () =>
      ROLES.map((r) => ({
        role: r,
        precision_high_confidence: kpis?.[r]?.precision_high_confidence ?? "—",
        abstention_rate: kpis?.[r]?.abstention_rate ?? "—",
        drift_score: kpis?.[r]?.drift_score ?? "—",
        total_samples: kpis?.[r]?.total_samples ?? "—",
      })),
    [kpis],
  );

  return (
    <div>
      <SectionHeader
        title="Learn (Teach AI)"
        subtitle="Training state, model version lifecycle, and threshold controls via Gateway."
        right={message ? <span className="muted">{message}</span> : null}
      />

      <Panel title="Learning State">
        <div className="filters-row">
          <StatusPill text={state?.training_enabled ? "Training Enabled" : "Training Disabled"} tone={state?.training_enabled ? "good" : "warn"} />
          <span className="muted">Last training run: {state?.last_training_run || "—"}</span>
          <span className="muted">Role scope:</span>
          <select data-testid="learn-role" className="dark-select" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <button data-testid="learn-refresh" className="action-btn" onClick={() => void load()}>
            Refresh
          </button>
        </div>
      </Panel>

      <Panel title="Actions" subtitle="Manual training lifecycle controls routed only through Gateway.">
        <div className="filters-row">
          <button data-testid="learn-train" className="action-btn primary" disabled={busy} onClick={() => void runTrain()}>
            Run Training
          </button>
          <button data-testid="learn-promote" className="action-btn warn" disabled={busy} onClick={() => void runPromote()}>
            Promote Candidate
          </button>
          <button data-testid="learn-rollback" className="action-btn bad" disabled={busy} onClick={() => void runRollback()}>
            Rollback Deployed
          </button>
          {role === "live" ? <StatusPill text="LIVE role selected" tone="warn" /> : null}
        </div>
      </Panel>

      <Panel title="Training Policy" subtitle="Training window, labeling, calibration, veto filters, and dynamic thresholds by regime.">
        <div className="grid-2">
          <label className="muted">
            Window (days)
            <input className="dark-input" value={String(windowDays)} onChange={(e) => setWindowDays(Number(e.target.value || 30))} />
          </label>
          <label className="muted">
            Label Rule
            <input
              className="dark-input"
              value={String(config?.label_rule || "pnl_gt_0")}
              onChange={(e) => setConfig((p: any) => ({ ...(p || {}), label_rule: e.target.value }))}
            />
          </label>
          <label className="muted">
            High-Confidence Threshold
            <input
              className="dark-input"
              value={String(config?.high_conf_threshold ?? 0.75)}
              onChange={(e) => setConfig((p: any) => ({ ...(p || {}), high_conf_threshold: Number(e.target.value || 0.75) }))}
            />
          </label>
          <label className="muted">
            Abstain Threshold
            <input
              className="dark-input"
              value={String(config?.abstain_threshold ?? 0.55)}
              onChange={(e) => setConfig((p: any) => ({ ...(p || {}), abstain_threshold: Number(e.target.value || 0.55) }))}
            />
          </label>
        </div>
        <div className="filters-row" style={{ marginTop: 10 }}>
          <button data-testid="learn-save-policy" className="action-btn primary" disabled={busy} onClick={() => void saveConfig()}>
            Save Policy
          </button>
          <button data-testid="learn-refresh-policy" className="action-btn" disabled={busy} onClick={() => void load()}>
            Refresh
          </button>
        </div>
      </Panel>

      <div className="grid-2">
        <Panel title="Model Versions by Role">
          <DataTable
            rows={modelRows}
            emptyText="No model version state found."
            columns={[
              { key: "role", title: "Role", render: (row: any) => row.role },
              { key: "deployed", title: "Deployed", render: (row: any) => row.deployed },
              { key: "candidate", title: "Candidate", render: (row: any) => row.candidate },
              { key: "previous", title: "Previous", render: (row: any) => row.previous },
            ]}
          />
        </Panel>

        <Panel title="Thresholds per Regime">
          <DataTable
            rows={thresholdRows}
            emptyText="No thresholds stored."
            columns={[
              { key: "regime", title: "Regime", render: (row: any) => row.regime },
              { key: "value", title: "Thresholds", render: (row: any) => row.value },
            ]}
          />
        </Panel>
      </div>

      <Panel title="Learn KPIs">
        <DataTable
          rows={kpiRows}
          emptyText="No KPI rows available."
          columns={[
            { key: "role", title: "Role", render: (row: any) => row.role },
            { key: "precision_high_confidence", title: "Precision@High Conf", render: (row: any) => `${row.precision_high_confidence}%` },
            { key: "abstention_rate", title: "Abstention Rate", render: (row: any) => `${row.abstention_rate}%` },
            { key: "drift_score", title: "Drift Score", render: (row: any) => row.drift_score },
            { key: "total_samples", title: "Samples", render: (row: any) => row.total_samples },
          ]}
        />
      </Panel>

      <Panel title="Last Metrics">
        <DataTable
          rows={Object.entries(state?.last_metrics || {}).map(([k, v]) => ({ k, v }))}
          emptyText="No training metrics yet."
          columns={[
            { key: "k", title: "Metric", render: (row: any) => row.k },
            { key: "v", title: "Value", render: (row: any) => (typeof row.v === "object" ? JSON.stringify(row.v) : String(row.v)) },
          ]}
        />
      </Panel>

      <Panel title="Brain Overview (Context)">
        <DataTable
          rows={Object.entries(status?.brain || {}).map(([k, v]) => ({ k, v }))}
          emptyText="No brain overview available."
          columns={[
            { key: "k", title: "Key", render: (row: any) => row.k },
            { key: "v", title: "Value", render: (row: any) => (typeof row.v === "object" ? JSON.stringify(row.v) : String(row.v)) },
          ]}
        />
      </Panel>
    </div>
  );
}
