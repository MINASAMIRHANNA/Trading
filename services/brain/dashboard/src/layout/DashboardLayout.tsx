import { lazy, Suspense, useMemo, useState } from "react";
import {
  Box,
  Drawer,
  List,
  ListItemButton,
  ListItemText,
  Typography,
} from "@mui/material";

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

const drawerWidth = 240;

export default function DashboardLayout() {
  const [page, setPage] = useState("overview");

  const Current = useMemo(() => {
    switch (page) {
      case "overview":
        return UnifiedOverview;
      case "signals":
        return MinaSignals;
      case "trades_positions":
        return TradesPositions;
      case "performance":
        return Performance;
      case "commands":
        return MinaCommands;
      case "control":
        return ControlCenter;
      case "settings":
        return SettingsCenter;
      case "pump":
        return PumpCenter;
      case "audit_events":
        return AuditEvents;
      case "brain":
        return BrainHub;
      case "ai_coach":
        return AICoachChat;
      case "ai_coach_daily":
        return AICoach;
      case "autopilot":
        return Autopilot;
      case "simulator":
        return Simulator;
      case "strategy_compare":
        return StrategyComparison;
      case "daily_summary":
        return DailySummary;
      case "daily_education":
        return DailyEducationPage;
      default:
        return UnifiedOverview;
    }
  }, [page]);

  return (
    <Box sx={{ display: "flex" }}>
      <Drawer
        variant="permanent"
        sx={{
          width: drawerWidth,
          flexShrink: 0,
          "& .MuiDrawer-paper": {
            width: drawerWidth,
            boxSizing: "border-box",
            backgroundColor: "#0d1117",
            color: "#e6edf3",
          },
        }}
      >
        <Typography variant="h6" sx={{ p: 2 }}>
          Unified Control
        </Typography>

        <List>
          <NavItem label="Overview" onClick={() => setPage("overview")} />
          <NavItem label="Signals" onClick={() => setPage("signals")} />
          <NavItem label="Trades & Positions" onClick={() => setPage("trades_positions")} />
          <NavItem label="Performance" onClick={() => setPage("performance")} />
          <NavItem label="Commands" onClick={() => setPage("commands")} />
          <NavItem label="Control Center" onClick={() => setPage("control")} />
          <NavItem label="Settings" onClick={() => setPage("settings")} />
          <NavItem label="Pump Center" onClick={() => setPage("pump")} />
          <NavItem label="Audit & Events" onClick={() => setPage("audit_events")} />
          <NavItem label="Brain" onClick={() => setPage("brain")} />
          <NavItem label="AI Coach (Daily)" onClick={() => setPage("ai_coach_daily")} />
          <NavItem label="AI Coach" onClick={() => setPage("ai_coach")} />
          <NavItem label="Autopilot" onClick={() => setPage("autopilot")} />
          <NavItem label="Simulator" onClick={() => setPage("simulator")} />
          <NavItem label="Strategy Compare" onClick={() => setPage("strategy_compare")} />
          <NavItem label="Daily Summary" onClick={() => setPage("daily_summary")} />
          <NavItem label="Daily Education" onClick={() => setPage("daily_education")} />
        </List>
      </Drawer>

      <Box sx={{ flexGrow: 1, p: 4 }}>
        <Suspense fallback={<Typography>Loading…</Typography>}>
          <Current />
        </Suspense>
      </Box>
    </Box>
  );
}

function NavItem({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <ListItemButton onClick={onClick}>
      <ListItemText primary={label} />
    </ListItemButton>
  );
}
