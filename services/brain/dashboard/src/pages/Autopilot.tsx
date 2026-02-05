import { useEffect, useState } from "react";
import {
  Box,
  Paper,
  Typography,
  Stack,
  MenuItem,
  TextField,
  Button,
  Divider,
} from "@mui/material";
import {
  getAutopilot,
  setAutopilotGlobal,
  setAutopilotRole,
  fetchUnifiedSettings,
  updateUnifiedSettings,
} from "../api/unified";
import type { UnifiedRole } from "../api/unified";

const MODES = ["OFF", "SHADOW", "TESTNET", "LIVE"] as const;
const ROLES: UnifiedRole[] = ["paper", "live", "pump"];

export default function Autopilot() {
  const [loading, setLoading] = useState(false);
  const [autopilot, setAutopilot] = useState<any>(null);
  const [settings, setSettings] = useState<Record<UnifiedRole, any>>({
    paper: {},
    live: {},
    pump: {},
  });
  const [activeStrategy, setActiveStrategy] = useState<Record<UnifiedRole, string>>({
    paper: "",
    live: "",
    pump: "",
  });

  const reload = async () => {
    setLoading(true);
    try {
      const ap = await getAutopilot();
      setAutopilot(ap);
      const all: any = {};
      for (const role of ROLES) {
        const s = await fetchUnifiedSettings(role);
        all[role] = s || {};
      }
      setSettings(all);
      setActiveStrategy({
        paper: String(all.paper?.active_strategy || ""),
        live: String(all.live?.active_strategy || ""),
        pump: String(all.pump?.active_strategy || ""),
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
  }, []);

  const onSetGlobal = async (mode: string) => {
    await setAutopilotGlobal(mode as any);
    await reload();
  };

  const onSetRole = async (role: UnifiedRole, mode: string) => {
    await setAutopilotRole(role, mode as any);
    await reload();
  };

  const onSaveStrategy = async (role: UnifiedRole) => {
    const val = (activeStrategy[role] || "").trim();
    await updateUnifiedSettings(role, {
      active_strategy: val,
      strategy_last_changed_utc: new Date().toISOString(),
      strategy_changed_by: "ui",
    });
    await reload();
  };

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Autopilot Control
      </Typography>

      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          Global Mode
        </Typography>
        <Stack direction="row" spacing={2} alignItems="center">
          <TextField
            select
            size="small"
            label="Global Mode"
            value={autopilot?.global_mode || "OFF"}
            onChange={(e) => onSetGlobal(e.target.value)}
            sx={{ minWidth: 200 }}
            disabled={loading}
          >
            {MODES.map((m) => (
              <MenuItem key={m} value={m}>
                {m}
              </MenuItem>
            ))}
          </TextField>
          <Typography variant="body2" color="text.secondary">
            Effective mode = min(global, role)
          </Typography>
        </Stack>
      </Paper>

      <Stack spacing={2}>
        {ROLES.map((role) => {
          const roleMode = autopilot?.roles?.[role]?.role_mode || "OFF";
          const effective = autopilot?.roles?.[role]?.effective_mode || "OFF";
          return (
            <Paper key={role} sx={{ p: 2 }}>
              <Typography variant="subtitle1" sx={{ mb: 1 }}>
                Role: {role.toUpperCase()}
              </Typography>
              <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }}>
                <TextField
                  select
                  size="small"
                  label="Role Mode"
                  value={roleMode}
                  onChange={(e) => onSetRole(role, e.target.value)}
                  sx={{ minWidth: 180 }}
                  disabled={loading}
                >
                  {MODES.map((m) => (
                    <MenuItem key={m} value={m}>
                      {m}
                    </MenuItem>
                  ))}
                </TextField>
                <Typography variant="body2">
                  Effective: <b>{effective}</b>
                </Typography>
              </Stack>

              <Divider sx={{ my: 1 }} />

              <Typography variant="subtitle2" sx={{ mt: 1 }}>
                Active Strategy
              </Typography>
              <Stack direction="row" spacing={2} alignItems="center" sx={{ mt: 1 }}>
                <TextField
                  size="small"
                  label="active_strategy"
                  value={activeStrategy[role] || ""}
                  onChange={(e) =>
                    setActiveStrategy((prev) => ({ ...prev, [role]: e.target.value }))
                  }
                  sx={{ minWidth: 260 }}
                />
                <Button
                  variant="contained"
                  onClick={() => onSaveStrategy(role)}
                  disabled={loading}
                >
                  Save
                </Button>
                <Typography variant="caption" color="text.secondary">
                  Current: {String(settings[role]?.active_strategy || "—")}
                </Typography>
              </Stack>
            </Paper>
          );
        })}
      </Stack>
    </Box>
  );
}
