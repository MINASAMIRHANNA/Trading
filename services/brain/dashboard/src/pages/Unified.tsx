import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  CircularProgress,
  Divider,
  Paper,
  Tab,
  Tabs,
  Typography,
  Snackbar,
  TextField,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
} from "@mui/material";

import { fetchUnifiedOverview, fetchUnifiedRoleSnapshot, approveUnifiedSignal, rejectUnifiedSignal, queueUnifiedCommand } from "../api/unified";
import type { UnifiedOverview, UnifiedRole } from "../api/unified";
import { fetchAuthStatus, loginAuth, logoutAuth } from "../api/auth";
import type { AuthStatus } from "../api/auth";

function JsonBlock({ value }: { value: any }) {
  const text = useMemo(() => {
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }, [value]);

  return (
    <Box
      component="pre"
      sx={{
        m: 0,
        p: 2,
        overflowX: "auto",
        whiteSpace: "pre-wrap",
        wordBreak: "break-word",
        fontSize: 12,
      }}
    >
      {text}
    </Box>
  );
}

export default function Unified() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [overview, setOverview] = useState<UnifiedOverview | null>(null);
  const [snapshot, setSnapshot] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [toast, setToast] = useState<{ severity: "success" | "error"; message: string } | null>(null);

  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [authLoading, setAuthLoading] = useState(false);

  const refreshAuth = async () => {
    try {
      const s = await fetchAuthStatus();
      setAuth(s);
      return s;
    } catch {
      setAuth(null);
      return null;
    }
  };

  const onLogin = async () => {
    setAuthLoading(true);
    setErr(null);
    try {
      await loginAuth(apiKey);
      setToast({ severity: "success", message: "Logged in" });
      await refreshAuth();
      await refresh();
    } catch (e: any) {
      setToast({ severity: "error", message: e?.message || "Login failed" });
    } finally {
      setAuthLoading(false);
    }
  };

  const onLogout = async () => {
    setAuthLoading(true);
    try {
      await logoutAuth();
      setToast({ severity: "success", message: "Logged out" });
      setApiKey("");
      await refreshAuth();
    } catch (e: any) {
      setToast({ severity: "error", message: e?.message || "Logout failed" });
    } finally {
      setAuthLoading(false);
    }
  };

  const refresh = async (roleOverride?: UnifiedRole) => {
    const r = roleOverride ?? role;
    setLoading(true);
    setErr(null);
    try {
      const [ov, snap] = await Promise.all([
        fetchUnifiedOverview(),
        fetchUnifiedRoleSnapshot(r),
      ]);
      setOverview(ov);
      setSnapshot(snap);
    } catch (e: any) {
      setErr(e?.message || "Failed to load unified data");
    } finally {
      setLoading(false);
    }
  };

  // initial load
  useEffect(() => {
    refreshAuth();
    refresh("paper");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // reload snapshot when role changes (keep overview cached)
  useEffect(() => {
    (async () => {
      setLoading(true);
      setErr(null);
      try {
        const snap = await fetchUnifiedRoleSnapshot(role);
        setSnapshot(snap);
      } catch (e: any) {
        setErr(e?.message || "Failed to load role snapshot");
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  const brain = overview?.brain;
  const dash = overview?.dashboards?.[role];

const getSignalId = (s: any): number | null => {
  const v =
    s?.id ??
    s?.signal_id ??
    s?.inbox_id ??
    s?._dashboard_inbox_id ??
    s?._dashboard_signal_id;
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
};

const getStatus = (s: any): string => {
  return String(s?.status ?? s?.state ?? "").toUpperCase();
};

const getSymbol = (s: any): string => {
  return String(s?.symbol ?? s?.pair ?? s?.s ?? "—");
};

const getSide = (s: any): string => {
  return String(s?.side ?? s?.direction ?? s?.signal ?? "—").toUpperCase();
};

const getConfidence = (s: any): any => {
  return s?.confidence ?? s?.score ?? s?.ai_confidence ?? null;
};

const onApprove = async (s: any) => {
  const sid = getSignalId(s);
  if (!sid) {
    setToast({ severity: "error", message: "Signal has no id" });
    return;
  }
  const note = window.prompt("Approve note (optional):", "") || "";
  try {
    await approveUnifiedSignal(role, sid, note || undefined);
    setToast({ severity: "success", message: `Approved signal #${sid}` });
    await refresh();
  } catch (e: any) {
    setToast({ severity: "error", message: e?.message || "Approve failed" });
  }
};

const onReject = async (s: any) => {
  const sid = getSignalId(s);
  if (!sid) {
    setToast({ severity: "error", message: "Signal has no id" });
    return;
  }
  const reason = window.prompt("Reject reason:", "Rejected from Unified UI") || "Rejected from Unified UI";
  try {
    await rejectUnifiedSignal(role, sid, reason);
    setToast({ severity: "success", message: `Rejected signal #${sid}` });
    await refresh();
  } catch (e: any) {
    setToast({ severity: "error", message: e?.message || "Reject failed" });
  }
};

const onForceCloseAll = async () => {
  const reason = window.prompt("Reason for CLOSE_ALL_POSITIONS:", "Manual override") || "Manual override";
  try {
    const r = await queueUnifiedCommand(role, "CLOSE_ALL_POSITIONS", { reason, ts_utc: new Date().toISOString() });
    setToast({ severity: "success", message: r?.message ? String(r.message) : "Queued CLOSE_ALL_POSITIONS" });
  } catch (e: any) {
    setToast({ severity: "error", message: e?.message || "Queue command failed" });
  } finally {
    await refresh();
  }
};

  return (
    <Box>
      <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
        <Typography variant="h4">Unified Stack</Typography>
        <Box sx={{ flexGrow: 1 }} />
        <Button variant="contained" onClick={() => refresh()}>
          Refresh
        </Button>
      </Box>

      <Typography sx={{ opacity: 0.7, mt: 1 }}>
        Source: Gateway <code>/api/unified/*</code>
        {overview?.ts_utc ? ` • ${overview.ts_utc}` : ""}
      </Typography>

      <Paper sx={{ p: 2, mt: 2 }}>
        <Typography variant="h6">Gateway authentication</Typography>
        <Typography sx={{ opacity: 0.7, mb: 1 }}>
          {auth?.enabled
            ? auth.authenticated
              ? `Authenticated (${auth.method})`
              : "Authentication required"
            : "Auth disabled"}
        </Typography>

        {auth?.enabled && !auth?.authenticated && (
          <Box sx={{ display: "flex", gap: 2, alignItems: "center", flexWrap: "wrap" }}>
            <TextField
              size="small"
              label="API Key"
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              sx={{ minWidth: 360 }}
            />
            <Button
              variant="contained"
              onClick={onLogin}
              disabled={authLoading || !apiKey.trim()}
            >
              Login
            </Button>
            <Button variant="outlined" onClick={refreshAuth} disabled={authLoading}>
              Check
            </Button>
          </Box>
        )}

        {auth?.enabled && auth?.authenticated && (
          <Box sx={{ display: "flex", gap: 2, alignItems: "center", flexWrap: "wrap" }}>
            <Button variant="outlined" onClick={onLogout} disabled={authLoading}>
              Logout
            </Button>
            <Button variant="outlined" onClick={refreshAuth} disabled={authLoading}>
              Refresh status
            </Button>
          </Box>
        )}
      </Paper>
      <Divider sx={{ my: 3 }} />

      {loading && (
        <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
          <CircularProgress size={22} />
          <Typography>Loading…</Typography>
        </Box>
      )}

      {err && (
        <Paper sx={{ p: 2, mb: 3, border: "1px solid rgba(255,0,0,0.25)" }}>
          <Typography color="error">{err}</Typography>
        </Paper>
      )}

      <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 2 }}>
        <Paper sx={{ p: 2 }}>
          <Typography variant="h6">Brain overview</Typography>
          <Typography sx={{ opacity: 0.7, mb: 1 }}>
            Quick health/metrics from Brain API
          </Typography>
          <JsonBlock value={brain ?? { note: "No data yet" }} />
        </Paper>

        <Paper sx={{ p: 2 }}>
          <Typography variant="h6">Dashboards overview</Typography>
          <Typography sx={{ opacity: 0.7, mb: 1 }}>
            Per-role stats + signals preview
          </Typography>

          <Tabs
            value={role}
            onChange={(_, v) => setRole(v)}
            textColor="inherit"
            indicatorColor="primary"
          >
            <Tab value="paper" label="Paper" />
            <Tab value="live" label="Live" />
            <Tab value="pump" label="Pump" />
          </Tabs>

          <Divider sx={{ my: 2 }} />

          <Typography variant="subtitle1">Stats</Typography>
          <JsonBlock value={dash?.stats ?? { note: "No stats" }} />

          <Divider sx={{ my: 2 }} />

          <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
  <Typography variant="subtitle1">Signals preview</Typography>
  <Button size="small" variant="outlined" onClick={onForceCloseAll}>
    Force Close All
  </Button>
</Box>

  {Array.isArray(dash?.signals_preview) && dash!.signals_preview.length > 0 ? (
    <Table size="small">
      <TableHead>
        <TableRow>
          <TableCell>ID</TableCell>
          <TableCell>Symbol</TableCell>
          <TableCell>Side</TableCell>
          <TableCell>Status</TableCell>
          <TableCell>Conf</TableCell>
          <TableCell align="right">Actions</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>
        {dash!.signals_preview.map((s: any, idx: number) => {
          const sid = getSignalId(s);
          const st = getStatus(s);
          const pending = st === "PENDING_APPROVAL" || st === "PENDING";
          return (
            <TableRow key={sid ?? idx}>
              <TableCell>{sid ?? "—"}</TableCell>
              <TableCell>{getSymbol(s)}</TableCell>
              <TableCell>{getSide(s)}</TableCell>
              <TableCell>{st || "—"}</TableCell>
              <TableCell>{getConfidence(s) ?? "—"}</TableCell>
              <TableCell align="right">
                {pending ? (
                  <Box sx={{ display: "flex", gap: 1, justifyContent: "flex-end" }}>
                    <Button size="small" variant="contained" onClick={() => onApprove(s)}>
                      Approve
                    </Button>
                    <Button size="small" color="error" variant="outlined" onClick={() => onReject(s)}>
                      Reject
                    </Button>
                  </Box>
                ) : (
                  <Typography sx={{ opacity: 0.6 }} variant="body2">
                    —
                  </Typography>
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  ) : (
    <Typography sx={{ opacity: 0.7 }}>No signals</Typography>
  )}
        </Paper>
      </Box>

      <Divider sx={{ my: 3 }} />

      <Paper sx={{ p: 2 }}>
        <Typography variant="h6">Role snapshot: {role}</Typography>
        <Typography sx={{ opacity: 0.7, mb: 1 }}>
  One-call snapshot: system_health + stats + positions + signals
</Typography>

<Typography variant="subtitle1" sx={{ mt: 1 }}>
  Snapshot signals
</Typography>
{Array.isArray(snapshot?.signals) && snapshot.signals.length > 0 ? (
  <Table size="small" sx={{ mt: 1 }}>
    <TableHead>
      <TableRow>
        <TableCell>ID</TableCell>
        <TableCell>Symbol</TableCell>
        <TableCell>Side</TableCell>
        <TableCell>Status</TableCell>
        <TableCell>Conf</TableCell>
        <TableCell align="right">Actions</TableCell>
      </TableRow>
    </TableHead>
    <TableBody>
      {snapshot.signals.map((s: any, idx: number) => {
        const sid = getSignalId(s);
        const st = getStatus(s);
        const pending = st === "PENDING_APPROVAL" || st === "PENDING";
        return (
          <TableRow key={sid ?? idx}>
            <TableCell>{sid ?? "—"}</TableCell>
            <TableCell>{getSymbol(s)}</TableCell>
            <TableCell>{getSide(s)}</TableCell>
            <TableCell>{st || "—"}</TableCell>
            <TableCell>{getConfidence(s) ?? "—"}</TableCell>
            <TableCell align="right">
              {pending ? (
                <Box sx={{ display: "flex", gap: 1, justifyContent: "flex-end" }}>
                  <Button size="small" variant="contained" onClick={() => onApprove(s)}>
                    Approve
                  </Button>
                  <Button size="small" color="error" variant="outlined" onClick={() => onReject(s)}>
                    Reject
                  </Button>
                </Box>
              ) : (
                <Typography sx={{ opacity: 0.6 }} variant="body2">
                  —
                </Typography>
              )}
            </TableCell>
          </TableRow>
        );
      })}
    </TableBody>
  </Table>
) : (
  <Typography sx={{ opacity: 0.7 }}>No signals in snapshot</Typography>
)}

<Divider sx={{ my: 2 }} />

<Typography variant="subtitle1">Raw snapshot JSON</Typography>
<JsonBlock value={snapshot ?? { note: "No snapshot yet" }} />
      </Paper>
      <Snackbar
        open={!!toast}
        autoHideDuration={3500}
        onClose={() => setToast(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        {toast ? (
          <Alert severity={toast.severity} onClose={() => setToast(null)} sx={{ width: "100%" }}>
            {toast.message}
          </Alert>
        ) : null}
      </Snackbar>
    </Box>
  );
}
