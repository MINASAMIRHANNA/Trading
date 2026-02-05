import { useState } from "react";
import { Box, Tab, Tabs, Typography } from "@mui/material";
import Overview from "./Overview";
import DecisionCenter from "./DecisionCenter";
import MLExplainability from "./MLExplainability";

export default function BrainHub() {
  const [tab, setTab] = useState(0);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" sx={{ mb: 1 }}>
        Brain
      </Typography>
      <Typography sx={{ opacity: 0.8, mb: 2 }}>
        Brain analytics: overview, decisions, and ML explainability.
      </Typography>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Overview" />
        <Tab label="Decision" />
        <Tab label="ML Importance" />
      </Tabs>

      {tab === 0 && <Overview />}
      {tab === 1 && <DecisionCenter />}
      {tab === 2 && <MLExplainability />}
    </Box>
  );
}
