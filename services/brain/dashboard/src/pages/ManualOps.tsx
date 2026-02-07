import { useState } from "react";
import type { UnifiedRole } from "../api/unified";
import { Panel, SectionHeader } from "../components/mina";
import HistoricalSnapshotUTC from "./HistoricalSnapshotUTC";
import LiveBrainInspector from "./LiveBrainInspector";
import ManualExecution from "./ManualExecution";
import TeachAI from "./TeachAI";

type ManualTab = "inspector" | "execution" | "teach" | "snapshot";

const TABS: Array<{ key: ManualTab; label: string }> = [
  { key: "inspector", label: "Live Brain Inspector" },
  { key: "execution", label: "Manual Execution" },
  { key: "teach", label: "Teach AI" },
  { key: "snapshot", label: "Historical Snapshot (UTC)" },
];

export default function ManualOps() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [tab, setTab] = useState<ManualTab>("execution");

  return (
    <div>
      <SectionHeader
        title="Manual Ops"
        subtitle="Legacy manual operations grouped in one place, with bot selection."
      />

      <Panel title="Scope">
        <div className="filters-row">
          <select data-testid="manual-ops-role" className="dark-select" value={role} onChange={(e) => setRole(e.target.value as UnifiedRole)}>
            <option value="paper">paper</option>
            <option value="live">live</option>
            <option value="pump">pump</option>
          </select>
          {TABS.map((item) => (
            <button
              data-testid={`manual-ops-tab-${item.key}`}
              key={item.key}
              className={`action-btn${tab === item.key ? " primary" : ""}`}
              onClick={() => setTab(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </Panel>

      {tab === "inspector" ? <LiveBrainInspector initialRole={role} lockRole /> : null}
      {tab === "execution" ? <ManualExecution initialRole={role} lockRole /> : null}
      {tab === "teach" ? <TeachAI initialRole={role} lockRole /> : null}
      {tab === "snapshot" ? <HistoricalSnapshotUTC initialRole={role} lockRole /> : null}
    </div>
  );
}
