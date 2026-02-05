import { useEffect, useState } from "react";
import {
  Box,
  Divider,
  Paper,
  Typography,
  CircularProgress,
  Button,
} from "@mui/material";
import Grid from "@mui/material/GridLegacy";
import { fetchUnifiedOverview, fetchUnifiedSystemHealth, type UnifiedRole } from "../api/unified";

type RoleHealth = {
  role: UnifiedRole;
  data: any;
};

export default function UnifiedOverview() {
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [overview, setOverview] = useState<any>(null);
  const [health, setHealth] = useState<RoleHealth[]>([]);

  const load = async () => {
    setLoading(true);
    setErr(null);
    try {
      const ov = await fetchUnifiedOverview();
      setOverview(ov);
      const roles: UnifiedRole[] = ["paper", "live", "pump"];
      const healthRows = await Promise.all(
        roles.map(async (role) => ({ role, data: await fetchUnifiedSystemHealth(role) }))
      );
      setHealth(healthRows);
    } catch (e: any) {
      setErr(e?.message || "Failed to load overview");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  if (loading) {
    return (
      <Box sx={{ p: 3, display: "flex", gap: 2, alignItems: "center" }}>
        <CircularProgress size={20} />
        <Typography>Loading overview…</Typography>
      </Box>
    );
  }

  if (err) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography color="error">{err}</Typography>
        <Button onClick={() => void load()} sx={{ mt: 2 }} variant="contained">
          Retry
        </Button>
      </Box>
    );
  }

  const brain = overview?.brain || {};
  const dashboards = overview?.dashboards || {};

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" sx={{ mb: 1 }}>
        Unified Overview
      </Typography>
      <Typography sx={{ opacity: 0.8, mb: 2 }}>
        Gateway-backed health + performance snapshot across paper/live/pump.
      </Typography>

      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2" sx={{ opacity: 0.7 }}>
              Brain (features)
            </Typography>
            <Typography variant="h5">{brain.trades ?? 0} trades</Typography>
            <Typography variant="body2">win_rate: {brain.win_rate ?? "-"}</Typography>
            <Typography variant="body2">expectancy: {brain.expectancy ?? "-"}</Typography>
          </Paper>
        </Grid>

        {(["paper", "live", "pump"] as UnifiedRole[]).map((role) => {
          const stats = dashboards?.[role]?.stats || {};
          const signals = dashboards?.[role]?.signals_preview || [];
          return (
            <Grid item xs={12} md={4} key={role}>
              <Paper sx={{ p: 2 }}>
                <Typography variant="subtitle2" sx={{ opacity: 0.7 }}>
                  {role} dashboard
                </Typography>
                <Typography variant="h5">{stats.trades ?? 0} trades</Typography>
                <Typography variant="body2">win_rate: {stats.win_rate ?? "-"}</Typography>
                <Typography variant="body2">pnl: {stats.pnl ?? "-"}</Typography>
                <Typography variant="body2" sx={{ mt: 1 }}>
                  signals preview: {Array.isArray(signals) ? signals.length : 0}
                </Typography>
              </Paper>
            </Grid>
          );
        })}
      </Grid>

      <Divider sx={{ my: 3 }} />

      <Typography variant="h6" sx={{ mb: 1 }}>
        System Health
      </Typography>
      <Grid container spacing={2}>
        {health.map(({ role, data }) => (
          <Grid item xs={12} md={4} key={role}>
            <Paper sx={{ p: 2 }}>
              <Typography variant="subtitle2" sx={{ opacity: 0.7 }}>
                {role}
              </Typography>
              <Typography variant="body2">online: {String(data?.online ?? "-")}</Typography>
              <Typography variant="body2">latency: {data?.latency ?? "-"} ms</Typography>
              <Typography variant="body2">last_seen: {data?.last_seen_seconds ?? "-"}s</Typography>
              <Typography variant="body2">errors: {data?.error_count ?? "-"}</Typography>
            </Paper>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}
