import { useState } from "react";
import {
  Box,
  Drawer,
  List,
  ListItemButton,
  ListItemText,
  Typography,
} from "@mui/material";

import Overview from "../pages/Overview";
import Simulator from "../pages/Simulator";
import RegimePerformance from "../pages/RegimePerformance";
import MLExplainability from "../pages/MLExplainability";
import DailySummary from "../pages/DailySummary";
import AICoach from "../pages/AICoach";
import StrategyComparison from "../pages/StrategyComparison";
import AICoachChat from "../pages/AICoachChat";
import DecisionCenter from "../pages/DecisionCenter";

const drawerWidth = 240;

export default function DashboardLayout() {
  const [page, setPage] = useState("overview");

  const renderPage = () => {
    switch (page) {
      case "overview":
        return <Overview />;
      case "simulator":
        return <Simulator />;
      case "regime":
        return <RegimePerformance />;
      case "ml":
        return <MLExplainability />;
      case "daily":
        return <DailySummary />;
      case "coach":
        return <AICoach />;
      case "strategy":
      return <StrategyComparison />; // 👈 دي كانت ناقصة
      case "chat":
        return <AICoachChat />;
      case "decision":
        return <DecisionCenter />;
      default:
        return <Overview />;
        
    }
  };

  return (
    <Box sx={{ display: "flex" }}>
      {/* Sidebar */}
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
          <NavItem label="Overview" onClick={() => setPage("overview")} />
          <NavItem label="Simulator" onClick={() => setPage("simulator")} />
          <NavItem
            label="Regime Performance"
            onClick={() => setPage("regime")}
          />
          <NavItem
            label="ML Explainability"
            onClick={() => setPage("ml")}
          />
          <NavItem label="Daily Summary" onClick={() => setPage("daily")} />
          <NavItem label="AI Coach" onClick={() => setPage("coach")} />
          <NavItem label="Strategy Comparison" onClick={() => setPage("strategy")} />
          <NavItem label="AI Coach Chat" onClick={() => setPage("chat")} />
          <NavItem label="Decision Center" onClick={() => setPage("decision")} />
        </List>
      </Drawer>

      {/* Content */}
      <Box sx={{ flexGrow: 1, p: 4 }}>{renderPage()}</Box>
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
