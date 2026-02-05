import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Divider,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Snackbar,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import {
  type UnifiedRole,
  fetchUnifiedSettings,
  updateUnifiedSettings,
  clearUnifiedKillSwitch,
  restartUnifiedBot,
  restartUnifiedMonitor,
} from "../api/unified";

const ROLES: UnifiedRole[] = ["paper", "live", "pump"];

export default function ControlCenter() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [settings, setSettings] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [reason, setReason] = useState("manual_kill_switch");
  const [snack, setSnack] = useState<{ open: boolean; msg: string; severity: "success" | "error" }>(
    { open: false, msg: "", severity: "success" }
  );

  const killSwitchOn = useMemo(() => {
    const v = settings?.kill_switch;
    if (typeof v === "boolean") return v;
    if (typeof v === "number") return v === 1;
    if (typeof v === "string") return v.trim() === "1" || v.toLowerCase() === "true";
    return false;
  }, [settings]);

  const load = async () => {
    setLoading(true);
    try {
      const data = await fetchUnifiedSettings(role);
      setSettings(data);
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Failed to load settings"), severity: "error" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  const toggleKillSwitch = async (enabled: boolean) => {
    try {
      if (enabled) {
        await updateUnifiedSettings(role, { kill_switch: "1", kill_switch_reason: reason || "manual" });
        setSnack({ open: true, msg: `Kill switch enabled for ${role}`, severity: "success" });
      } else {
        await clearUnifiedKillSwitch(role);
        setSnack({ open: true, msg: `Kill switch cleared for ${role}`, severity: "success" });
      }
      await load();
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Failed to update kill switch"), severity: "error" });
    }
  };

  const doRestartBot = async () => {
    try {
      await restartUnifiedBot(role);
      setSnack({ open: true, msg: `Restart bot requested (${role})`, severity: "success" });
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Restart bot failed"), severity: "error" });
    }
  };

  const doRestartMonitor = async () => {
    try {
      await restartUnifiedMonitor(role);
      setSnack({ open: true, msg: `Restart monitor requested (${role})`, severity: "success" });
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Restart monitor failed"), severity: "error" });
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Control Center
      </Typography>
      <Typography variant="body2" sx={{ opacity: 0.8, mb: 2 }}>
        Unified control actions via Gateway. Kill switch blocks new positions only; closing is always allowed.
      </Typography>

      <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap", alignItems: "center" }}>
        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Role</InputLabel>
          <Select label="Role" value={role} onChange={(e) => setRole(e.target.value as UnifiedRole)}>
            {ROLES.map((r) => (
              <MenuItem key={r} value={r}>
                {r}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <TextField
          size="small"
          label="Kill Switch Reason"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          sx={{ minWidth: 240 }}
        />

        <FormControlLabel
          control={<Switch checked={killSwitchOn} onChange={(e) => void toggleKillSwitch(e.target.checked)} />}
          label={killSwitchOn ? "Kill Switch: ON" : "Kill Switch: OFF"}
        />

        <Button variant="outlined" onClick={() => void load()} disabled={loading}>
          Refresh
        </Button>
      </Box>

      <Divider sx={{ my: 3 }} />

      <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap" }}>
        <Button variant="contained" onClick={() => void doRestartBot()} disabled={loading}>
          Restart Bot
        </Button>
        <Button variant="contained" onClick={() => void doRestartMonitor()} disabled={loading}>
          Restart Monitor
        </Button>
      </Box>

      <Snackbar open={snack.open} autoHideDuration={4000} onClose={() => setSnack((s) => ({ ...s, open: false }))}>
        <Alert severity={snack.severity} onClose={() => setSnack((s) => ({ ...s, open: false }))} sx={{ width: "100%" }}>
          {snack.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
}
