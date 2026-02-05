import { useState } from "react";
import { Box, Tab, Tabs, Typography } from "@mui/material";
import Audit from "./Audit";
import Events from "./Events";

export default function AuditEvents() {
  const [tab, setTab] = useState(0);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" sx={{ mb: 1 }}>
        Audit & Events
      </Typography>
      <Typography sx={{ opacity: 0.8, mb: 2 }}>
        Gateway audit log and shared event stream (filter by trace ID).
      </Typography>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
        <Tab label="Audit Log" />
        <Tab label="Events" />
      </Tabs>

      {tab === 0 && <Audit />}
      {tab === 1 && <Events />}
    </Box>
  );
}
