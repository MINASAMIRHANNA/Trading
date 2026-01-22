import { useEffect, useState } from "react";
import { Paper, Typography, Chip, Stack } from "@mui/material";
import { api } from "../api/client";

type ExecutionStatusResponse = {
  execution_enabled: boolean;
  mode: string;
  ready: boolean;
  reason: string;
};

export default function ExecutionStatus() {
  const [status, setStatus] = useState<ExecutionStatusResponse | null>(null);

  useEffect(() => {
    api
      .get("/execution/status")
      .then((r) => setStatus(r.data))
      .catch(() =>
        setStatus({
          execution_enabled: false,
          mode: "unknown",
          ready: false,
          reason: "Failed to load execution status",
        })
      );
  }, []);

  if (!status) {
    return <Typography>Loading execution status…</Typography>;
  }

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        🔐 Execution Status
      </Typography>

      <Stack direction="row" spacing={2} sx={{ mb: 2 }}>
        <Chip
          label={status.execution_enabled ? "ENABLED" : "DISABLED"}
          color={status.execution_enabled ? "success" : "default"}
        />

        <Chip
          label={status.mode.toUpperCase()}
          color={status.mode === "dry-run" ? "warning" : "info"}
        />

        <Chip
          label={status.ready ? "READY" : "NOT READY"}
          color={status.ready ? "success" : "error"}
        />
      </Stack>

      <Typography color="text.secondary">
        {status.reason}
      </Typography>
    </Paper>
  );
}
