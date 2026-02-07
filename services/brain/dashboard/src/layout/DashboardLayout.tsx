import { lazy, Suspense } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";

const UnifiedOverview = lazy(() => import("../pages/UnifiedOverview"));
const MinaSignals = lazy(() => import("../pages/MinaSignals"));
const TradesPositions = lazy(() => import("../pages/TradesPositions"));
const Performance = lazy(() => import("../pages/Performance"));
const MinaCommands = lazy(() => import("../pages/MinaCommands"));
const AuditEvents = lazy(() => import("../pages/AuditEvents"));
const BrainHub = lazy(() => import("../pages/BrainHub"));
const ControlCenter = lazy(() => import("../pages/ControlCenter"));
const SettingsCenter = lazy(() => import("../pages/SettingsCenter"));
const PumpCenter = lazy(() => import("../pages/PumpCenter"));
const AICoachChat = lazy(() => import("../pages/AICoachChat"));
const AICoach = lazy(() => import("../pages/AICoach"));
const Autopilot = lazy(() => import("../pages/Autopilot"));
const Simulator = lazy(() => import("../pages/Simulator"));
const StrategyComparison = lazy(() => import("../pages/StrategyComparison"));
const DailySummary = lazy(() => import("../pages/DailySummary"));
const DailyEducationPage = lazy(() => import("../pages/DailyEducationPage"));
const OpsLive = lazy(() => import("../pages/OpsLive"));
const Portfolio = lazy(() => import("../pages/Portfolio"));
const ManualOps = lazy(() => import("../pages/ManualOps"));
const Reports = lazy(() => import("../pages/Reports"));
const MinaAnalytics = lazy(() => import("../pages/MinaAnalytics"));
const MinaAudit = lazy(() => import("../pages/MinaAudit"));
const ProjectDoctor = lazy(() => import("../pages/ProjectDoctor"));
const ApiHub = lazy(() => import("../pages/ApiHub"));
const Learn = lazy(() => import("../pages/Learn"));
const Alerts = lazy(() => import("../pages/Alerts"));
const LiveBrainInspector = lazy(() => import("../pages/LiveBrainInspector"));
const ManualExecution = lazy(() => import("../pages/ManualExecution"));
const TeachAI = lazy(() => import("../pages/TeachAI"));
const HistoricalSnapshotUTC = lazy(() => import("../pages/HistoricalSnapshotUTC"));
const StatusMaintenance = lazy(() => import("../pages/StatusMaintenance"));

const NAV_GROUPS = [
  {
    label: "Operations",
    items: [
      { to: "/ops-live", label: "Operations Center" },
      { to: "/portfolio", label: "Portfolio" },
      { to: "/manual-ops", label: "Manual Ops" },
      { to: "/manual-execution", label: "Manual Execution" },
      { to: "/reports", label: "Reports" },
      { to: "/analytics", label: "Analytics" },
      { to: "/audit", label: "Audit" },
      { to: "/historical-snapshot-utc", label: "Historical Snapshot (UTC)" },
      { to: "/project-doctor", label: "Project Doctor" },
      { to: "/status-maintenance", label: "Status & Maintenance" },
      { to: "/api", label: "API Explorer" },
      { to: "/learn", label: "Learn (Teach AI)" },
      { to: "/teach-ai", label: "Teach AI" },
      { to: "/alerts", label: "Telegram Notifications" },
    ],
  },
  {
    label: "Unified Control",
    items: [
      { to: "/", label: "Overview", end: true },
      { to: "/signals", label: "Signals" },
      { to: "/trades-positions", label: "Trades & Positions" },
      { to: "/performance", label: "Performance" },
      { to: "/commands", label: "Commands" },
      { to: "/control", label: "Control Center" },
      { to: "/settings", label: "Settings" },
      { to: "/pump", label: "Pump Center" },
      { to: "/audit-events", label: "Audit & Events" },
    ],
  },
  {
    label: "Brain",
    items: [
      { to: "/brain", label: "Brain Hub" },
      { to: "/live-brain-inspector", label: "Live Brain Inspector" },
      { to: "/ai-coach-daily", label: "AI Coach (Daily)" },
      { to: "/ai-coach", label: "AI Coach Chat" },
      { to: "/autopilot", label: "Autopilot" },
      { to: "/simulator", label: "Simulator" },
      { to: "/strategy-compare", label: "Strategy Compare" },
      { to: "/daily-summary", label: "Daily Summary" },
      { to: "/daily-education", label: "Daily Education" },
    ],
  },
];

export default function DashboardLayout() {
  return (
    <div className="dashboard-shell">
      <aside className="dashboard-sidebar">
        <div className="dashboard-brand">
          <h1>Trading Unified Dashboard</h1>
          <p>Gateway Control Plane + Mina + Brain</p>
        </div>

        {NAV_GROUPS.map((group) => (
          <section className="nav-group" key={group.label}>
            <h3 className="nav-group-title">{group.label}</h3>
            <div className="nav-list">
              {group.items.map((item) => (
                <NavEntry key={item.to} to={item.to} end={item.end}>
                  {item.label}
                </NavEntry>
              ))}
            </div>
          </section>
        ))}
      </aside>

      <main className="dashboard-main">
        <Suspense fallback={<div className="muted">Loading…</div>}>
          <Routes>
            <Route path="/" element={<UnifiedOverview />} />
            <Route path="/signals" element={<MinaSignals />} />
            <Route path="/trades-positions" element={<TradesPositions />} />
            <Route path="/performance" element={<Performance />} />
            <Route path="/commands" element={<MinaCommands />} />
            <Route path="/control" element={<ControlCenter />} />
            <Route path="/settings" element={<SettingsCenter />} />
            <Route path="/pump" element={<PumpCenter />} />
            <Route path="/audit-events" element={<AuditEvents />} />
            <Route path="/brain" element={<BrainHub />} />
            <Route path="/ai-coach" element={<AICoachChat />} />
            <Route path="/ai-coach-daily" element={<AICoach />} />
            <Route path="/autopilot" element={<Autopilot />} />
            <Route path="/simulator" element={<Simulator />} />
            <Route path="/strategy-compare" element={<StrategyComparison />} />
            <Route path="/daily-summary" element={<DailySummary />} />
            <Route path="/daily-education" element={<DailyEducationPage />} />
            <Route path="/ops-live" element={<OpsLive />} />
            <Route path="/operations-center" element={<OpsLive />} />
            <Route path="/portfolio" element={<Portfolio />} />
            <Route path="/manual-ops" element={<ManualOps />} />
            <Route path="/manual-execution" element={<ManualExecution />} />
            <Route path="/reports" element={<Reports />} />
            <Route path="/analytics" element={<MinaAnalytics />} />
            <Route path="/analytics-report" element={<MinaAnalytics />} />
            <Route path="/audit" element={<MinaAudit />} />
            <Route path="/audit-lab" element={<MinaAudit />} />
            <Route path="/historical-snapshot-utc" element={<HistoricalSnapshotUTC />} />
            <Route path="/project-doctor" element={<ProjectDoctor />} />
            <Route path="/status-maintenance" element={<StatusMaintenance />} />
            <Route path="/status" element={<StatusMaintenance />} />
            <Route path="/manual" element={<ManualOps />} />
            <Route path="/api" element={<ApiHub />} />
            <Route path="/api-explorer" element={<ApiHub />} />
            <Route path="/learn" element={<Learn />} />
            <Route path="/teach-ai" element={<TeachAI />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/telegram-notifications" element={<Alerts />} />
            <Route path="/live-brain-inspector" element={<LiveBrainInspector />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}

function NavEntry(props: { to: string; end?: boolean; children: string }) {
  return (
    <NavLink to={props.to} end={props.end} className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}>
      {props.children}
    </NavLink>
  );
}
