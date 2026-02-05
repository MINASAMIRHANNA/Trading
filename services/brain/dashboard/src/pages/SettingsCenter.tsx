import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Divider,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Snackbar,
  TextField,
  Typography,
} from "@mui/material";
import { type UnifiedRole, fetchUnifiedSettings, updateUnifiedSettings, fetchUnifiedEnvSecrets, updateUnifiedEnvSecrets } from "../api/unified";

const ROLES: UnifiedRole[] = ["paper", "live", "pump"];

type FieldDef = { key: string; label: string; type?: "text" | "number" | "select"; options?: string[] };

type SectionDef = { title: string; fields: FieldDef[] };

const SETTINGS_SECTIONS: SectionDef[] = [
  {
    title: "Core Trading Controls (AI Config)",
    fields: [
      { key: "mode", label: "Mode", type: "select", options: ["TEST", "PAPER", "LIVE"] },
      { key: "kill_switch", label: "Kill Switch", type: "select", options: ["0", "1"] },
      { key: "kill_switch_reason", label: "Kill Switch Reason" },
      { key: "scalp_size_usd", label: "Scalp Size USD", type: "number" },
      { key: "swing_size_usd", label: "Swing Size USD", type: "number" },
      { key: "max_trade_usd", label: "Max Trade USD", type: "number" },
      { key: "max_concurrent_trades", label: "Max Concurrent Trades", type: "number" },
      { key: "leverage_scalp", label: "Leverage Scalp", type: "number" },
      { key: "leverage_swing", label: "Leverage Swing", type: "number" },
      { key: "require_dashboard_approval", label: "Require Dashboard Approval", type: "select", options: ["0", "1"] },
      { key: "auto_approve_live", label: "Auto Approve Live", type: "select", options: ["0", "1"] },
      { key: "auto_approve_paper", label: "Auto Approve Paper", type: "select", options: ["0", "1"] },
    ],
  },
  {
    title: "Risk & Gate",
    fields: [
      { key: "gate_atr_min_pct", label: "Gate ATR Min %", type: "number" },
      { key: "gate_adx_min", label: "Gate ADX Min", type: "number" },
      { key: "rsi_max_buy", label: "RSI Max Buy", type: "number" },
      { key: "pump_score_min", label: "Pump Score Min", type: "number" },
      { key: "min_conf_scalp", label: "Min Conf Scalp", type: "number" },
      { key: "min_conf_swing", label: "Min Conf Swing", type: "number" },
      { key: "sl_scalp_mult", label: "SL Scalp Mult", type: "number" },
      { key: "tp_scalp_mult", label: "TP Scalp Mult", type: "number" },
      { key: "sl_swing_mult", label: "SL Swing Mult", type: "number" },
      { key: "tp_swing_mult", label: "TP Swing Mult", type: "number" },
      { key: "trail_trigger_roi", label: "Trail Trigger ROI", type: "number" },
      { key: "ensure_protection_orders", label: "Ensure Protection Orders", type: "select", options: ["0", "1"] },
      { key: "ensure_protection_every_sec", label: "Protection Every (sec)", type: "number" },
    ],
  },
  {
    title: "Paper Tournament",
    fields: [
      { key: "paper_tournament_enabled", label: "Paper Tournament Enabled", type: "select", options: ["TRUE", "FALSE"] },
      { key: "paper_daily_enabled", label: "Paper Daily Enabled", type: "select", options: ["TRUE", "FALSE"] },
      { key: "paper_daily_time_utc", label: "Paper Daily Time (UTC)" },
    ],
  },
  {
    title: "Pump Hunter",
    fields: [
      { key: "pump_hunter_enabled", label: "Enabled", type: "select", options: ["TRUE", "FALSE"] },
      { key: "pump_hunter_allow_ai_weak", label: "Allow AI Weak", type: "select", options: ["TRUE", "FALSE"] },
      { key: "pump_hunter_market", label: "Market (spot/futures)" },
      { key: "pump_hunter_interval", label: "Interval" },
      { key: "pump_hunter_top_n", label: "Top N", type: "number" },
      { key: "pump_hunter_scan_sec", label: "Scan Every (sec)", type: "number" },
      { key: "pump_hunter_max_per_scan", label: "Max Per Scan", type: "number" },
      { key: "pump_hunter_pump_score_min", label: "Pump Score Min", type: "number" },
      { key: "pump_hunter_ai_conf_min", label: "AI Conf Min", type: "number" },
      { key: "pump_hunter_oi_change_min", label: "OI Change Min", type: "number" },
      { key: "pump_hunter_funding_max_abs", label: "Funding Max Abs", type: "number" },
      { key: "pump_hunter_exit_profile", label: "Exit Profile" },
      { key: "pump_hunter_leverage", label: "Leverage", type: "number" },
      { key: "pump_hunter_mirror_inbox", label: "Mirror Inbox", type: "select", options: ["TRUE", "FALSE"] },
    ],
  },
];

function isSecretKey(k: string) {
  return /(key|secret|token|pass|pwd)/i.test(k);
}

export default function SettingsCenter() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [settings, setSettings] = useState<Record<string, any>>({});
  const [envSecrets, setEnvSecrets] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(false);
  const [showSecrets, setShowSecrets] = useState(false);
  const [snack, setSnack] = useState<{ open: boolean; msg: string; severity: "success" | "error" }>(
    { open: false, msg: "", severity: "success" }
  );

  const load = async () => {
    setLoading(true);
    try {
      const settingsData = await fetchUnifiedSettings(role);
      setSettings(settingsData || {});
      const envData = await fetchUnifiedEnvSecrets(role);
      setEnvSecrets(envData || {});
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

  const updateSettingField = (key: string, value: any) => {
    setSettings((s) => ({ ...s, [key]: value }));
  };

  const updateEnvField = (key: string, value: any) => {
    setEnvSecrets((s) => ({ ...s, [key]: value }));
  };

  const saveSettings = async () => {
    try {
      await updateUnifiedSettings(role, settings);
      setSnack({ open: true, msg: "Settings updated", severity: "success" });
      await load();
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Failed to update settings"), severity: "error" });
    }
  };

  const saveEnv = async () => {
    if (!showSecrets) {
      setSnack({ open: true, msg: "Enable Show Secrets to edit env settings", severity: "error" });
      return;
    }
    try {
      await updateUnifiedEnvSecrets(role, envSecrets);
      setSnack({ open: true, msg: "Env settings updated", severity: "success" });
      await load();
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Failed to update env settings"), severity: "error" });
    }
  };

  const envKeys = useMemo(() => Object.keys(envSecrets || {}).sort(), [envSecrets]);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Settings
      </Typography>
      <Typography variant="body2" sx={{ opacity: 0.8, mb: 2 }}>
        AI Config + ENV Settings (keys) via Gateway. This mirrors the legacy dashboard structure.
      </Typography>

      <Box sx={{ display: "flex", gap: 2, alignItems: "center", flexWrap: "wrap", mb: 2 }}>
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
        <Button variant="outlined" onClick={() => void load()} disabled={loading}>
          Refresh
        </Button>
      </Box>

      {SETTINGS_SECTIONS.map((section) => (
        <Box key={section.title} sx={{ mb: 3 }}>
          <Typography variant="subtitle1" sx={{ mb: 1 }}>
            {section.title}
          </Typography>
          <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 1.5 }}>
            {section.fields.map((f) => {
              const value = settings?.[f.key] ?? "";
              if (f.type === "select" && f.options) {
                return (
                  <FormControl key={f.key} size="small">
                    <InputLabel>{f.label}</InputLabel>
                    <Select
                      label={f.label}
                      value={String(value)}
                      onChange={(e) => updateSettingField(f.key, e.target.value)}
                    >
                      {f.options.map((opt) => (
                        <MenuItem key={opt} value={opt}>
                          {opt}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                );
              }
              return (
                <TextField
                  key={f.key}
                  size="small"
                  label={f.label}
                  type={f.type === "number" ? "number" : "text"}
                  value={value}
                  onChange={(e) => updateSettingField(f.key, e.target.value)}
                />
              );
            })}
          </Box>
        </Box>
      ))}

      <Button variant="contained" onClick={() => void saveSettings()} disabled={loading}>
        Save AI Config
      </Button>

      <Divider sx={{ my: 3 }} />

      <Typography variant="subtitle1" sx={{ mb: 1 }}>
        ENV Settings (DB - Zero-ENV)
      </Typography>
      <FormControlLabel
        control={<Checkbox checked={showSecrets} onChange={(e) => setShowSecrets(e.target.checked)} />}
        label="Show secrets (unmask to edit)"
      />
      <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 1.5, mt: 1 }}>
        {envKeys.map((k) => (
          <TextField
            key={k}
            size="small"
            label={k}
            value={showSecrets ? String(envSecrets?.[k] ?? "") : isSecretKey(k) ? "******" : String(envSecrets?.[k] ?? "")}
            onChange={(e) => updateEnvField(k, e.target.value)}
            disabled={!showSecrets && isSecretKey(k)}
          />
        ))}
      </Box>

      <Button sx={{ mt: 2 }} variant="contained" onClick={() => void saveEnv()} disabled={loading}>
        Save ENV Settings
      </Button>

      <Snackbar open={snack.open} autoHideDuration={4000} onClose={() => setSnack((s) => ({ ...s, open: false }))}>
        <Alert severity={snack.severity} onClose={() => setSnack((s) => ({ ...s, open: false }))} sx={{ width: "100%" }}>
          {snack.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
}
