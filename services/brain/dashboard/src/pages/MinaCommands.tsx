import { useState } from "react";
import {
  Box,
  Button,
  Divider,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Snackbar,
  Alert,
  TextField,
  Typography,
} from "@mui/material";
import { type UnifiedRole, queueUnifiedCommand, queueUnifiedCloseAll, queueUnifiedKillSwitch } from "../api/unified";

const COMMANDS = [
  "CLOSE_ALL_POSITIONS",
  "CANCEL_ALL_ORDERS",
  "KILL_SWITCH_ON",
  "KILL_SWITCH_OFF",
];

export default function MinaCommands() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [cmd, setCmd] = useState<string>(COMMANDS[0]);
  const [reason, setReason] = useState<string>("Manual override");
  const [loading, setLoading] = useState(false);
  const [last, setLast] = useState<any>(null);
  const [snack, setSnack] = useState<{ open: boolean; msg: string; severity: "success" | "error" }>({
    open: false,
    msg: "",
    severity: "success",
  });

  const submit = async () => {
    setLoading(true);
    try {
      const res = await queueUnifiedCommand(role, cmd, { reason, ts_utc: new Date().toISOString() });
      setLast(res);
      setSnack({ open: true, msg: `Queued ${cmd} (audit_id=${res?.audit_id ?? "?"})`, severity: "success" });
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Command failed"), severity: "error" });
    } finally {
      setLoading(false);
    }
  };

  const submitCloseAll = async () => {
    setLoading(true);
    try {
      const res = await queueUnifiedCloseAll(role, reason);
      setLast(res);
      setSnack({ open: true, msg: `Queued CLOSE_ALL (audit_id=${res?.audit_id ?? "?"})`, severity: "success" });
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Close all failed"), severity: "error" });
    } finally {
      setLoading(false);
    }
  };

  const submitKillSwitch = async (enabled: boolean) => {
    setLoading(true);
    try {
      const res = await queueUnifiedKillSwitch(role, enabled, reason);
      setLast(res);
      setSnack({
        open: true,
        msg: `Queued ${enabled ? "KILL_SWITCH_ON" : "KILL_SWITCH_OFF"} (audit_id=${res?.audit_id ?? "?"})`,
        severity: "success",
      });
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Kill switch failed"), severity: "error" });
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Mina Commands
      </Typography>
      <Typography variant="body2" sx={{ opacity: 0.8, mb: 2 }}>
        Queue operational commands via Gateway (audited).
      </Typography>

      <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap", alignItems: "center" }}>
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Role</InputLabel>
          <Select label="Role" value={role} onChange={(e) => setRole(e.target.value as UnifiedRole)}>
            <MenuItem value="paper">paper</MenuItem>
            <MenuItem value="live">live</MenuItem>
            <MenuItem value="pump">pump</MenuItem>
          </Select>
        </FormControl>

        <FormControl size="small" sx={{ minWidth: 240 }}>
          <InputLabel>Command</InputLabel>
          <Select label="Command" value={cmd} onChange={(e) => setCmd(String(e.target.value))}>
            {COMMANDS.map((c) => (
              <MenuItem key={c} value={c}>
                {c}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <TextField size="small" label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} sx={{ minWidth: 260 }} />

        <Button variant="contained" onClick={() => void submit()} disabled={loading}>
          Send
        </Button>

        <Button variant="outlined" onClick={() => void submitCloseAll()} disabled={loading}>
          Close All
        </Button>

        <Button variant="outlined" color="error" onClick={() => void submitKillSwitch(true)} disabled={loading}>
          Kill Switch ON
        </Button>

        <Button variant="outlined" color="success" onClick={() => void submitKillSwitch(false)} disabled={loading}>
          Kill Switch OFF
        </Button>
      </Box>

      <Divider sx={{ my: 2 }} />

      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Last response
      </Typography>
      <pre style={{ background: "#0d1117", color: "#e6edf3", padding: 12, borderRadius: 8, overflowX: "auto" }}>
        {JSON.stringify(last, null, 2)}
      </pre>

      <Snackbar open={snack.open} autoHideDuration={4000} onClose={() => setSnack((s) => ({ ...s, open: false }))}>
        <Alert severity={snack.severity} onClose={() => setSnack((s) => ({ ...s, open: false }))} sx={{ width: "100%" }}>
          {snack.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
}
