import { lazy, Suspense, useMemo, useState } from "react";
import {
  Box,
  Drawer,
  List,
  ListItemButton,
  ListItemText,
  Typography,
} from "@mui/material";

const Overview = lazy(() => import("../pages/Overview"));
const Unified = lazy(() => import("../pages/Unified"));
const Simulator = lazy(() => import("../pages/Simulator"));
const RegimePerformance = lazy(() => import("../pages/RegimePerformance"));
const MLExplainability = lazy(() => import("../pages/MLExplainability"));
const DailySummary = lazy(() => import("../pages/DailySummary"));
const AICoach = lazy(() => import("../pages/AICoach"));
const StrategyComparison = lazy(() => import("../pages/StrategyComparison"));
const AICoachChat = lazy(() => import("../pages/AICoachChat"));
const DecisionCenter = lazy(() => import("../pages/DecisionCenter"));
const Audit = lazy(() => import("../pages/Audit"));
const Events = lazy(() => import("../pages/Events"));
const MinaSignals = lazy(() => import("../pages/MinaSignals"));
const MinaPositions = lazy(() => import("../pages/MinaPositions"));
const MinaCommands = lazy(() => import("../pages/MinaCommands"));

const drawerWidth = 240;

export default function DashboardLayout() {
  const [page, setPage] = useState("overview");

  const Current = useMemo(() => {
    switch (page) {
      case "unified":
        return Unified;
      case "overview":
        return Overview;
      case "simulator":
        return Simulator;
      case "regime":
        return RegimePerformance;
      case "ml":
        return MLExplainability;
      case "daily":
        return DailySummary;
      case "coach":
        return AICoach;
      case "strategy":
        return StrategyComparison;
      case "chat":
        return AICoachChat;
      case "decision":
        return DecisionCenter;
      case "audit":
        return Audit;
      case "events":
        return Events;
      case "mina_signals":
        return MinaSignals;
      case "mina_positions":
        return MinaPositions;
      case "mina_commands":
        return MinaCommands;
      default:
        return Overview;
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
          Trading Intelligence
        </Typography>

        <List>
          <NavItem label="Unified Stack" onClick={() => setPage("unified")} />
          <NavItem label="Mina Signals" onClick={() => setPage("mina_signals")} />
          <NavItem label="Mina Positions" onClick={() => setPage("mina_positions")} />
          <NavItem label="Mina Commands" onClick={() => setPage("mina_commands")} />
          <NavItem label="Overview" onClick={() => setPage("overview")} />
          <NavItem label="Simulator" onClick={() => setPage("simulator")} />
          <NavItem
            label="Regime Performance"
            onClick={() => setPage("regime")}
          />
          <NavItem label="ML Explainability" onClick={() => setPage("ml")} />
          <NavItem label="Daily Summary" onClick={() => setPage("daily")} />
          <NavItem label="AI Coach" onClick={() => setPage("coach")} />
          <NavItem
            label="Strategy Comparison"
            onClick={() => setPage("strategy")}
          />
          <NavItem label="AI Coach Chat" onClick={() => setPage("chat")} />
          <NavItem label="Decision Center" onClick={() => setPage("decision")} />
          <NavItem label="Events" onClick={() => setPage("events")} />
          <NavItem label="Audit" onClick={() => setPage("audit")} />
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
