import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  MenuItem,
  Paper,
  Snackbar,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import {
  approvePumpCandidate,
  getPumpStats,
  getPumpStatus,
  listPumpCandidates,
  listPumpTrades,
  promotePumpCandidate,
  rejectPumpCandidate,
  setPumpLabel,
} from "../api/pump";

type Candidate = Record<string, any>;

const STATUSES = ["PENDING", "WATCH", "APPROVED", "REJECTED", "EXECUTED"];
const SIDES = ["LONG", "SHORT"];

export default function PumpCenter() {
  const [status, setStatus] = useState<any>(null);
  const [stats, setStats] = useState<any>(null);
  const [trades, setTrades] = useState<any[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(false);

  const [filterStatus, setFilterStatus] = useState("PENDING");
  const [minScore, setMinScore] = useState("");
  const [symbolQuery, setSymbolQuery] = useState("");

  const [noteById, setNoteById] = useState<Record<number, string>>({});
  const [labelById, setLabelById] = useState<Record<number, string>>({});
  const [sideById, setSideById] = useState<Record<number, string>>({});

  const [snack, setSnack] = useState<{ open: boolean; msg: string; severity: "success" | "error" }>({
    open: false,
    msg: "",
    severity: "success",
  });

  const load = async () => {
    setLoading(true);
    try {
      const st = await getPumpStatus();
      setStatus(st);
      try {
        const s = await getPumpStats();
        setStats(s);
      } catch {
        setStats(null);
      }
      try {
        const tr = await listPumpTrades({ limit: 10 });
        const items = Array.isArray(tr?.items) ? tr.items : Array.isArray(tr) ? tr : [];
        setTrades(items);
      } catch {
        setTrades([]);
      }

      const cand = await listPumpCandidates({ limit: 100, status: filterStatus });
      const items = Array.isArray(cand?.items) ? cand.items : Array.isArray(cand) ? cand : [];
      setCandidates(items);
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Failed to load pump data"), severity: "error" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterStatus]);

  const filtered = useMemo(() => {
    let items = candidates.slice();
    const min = minScore ? Number(minScore) : null;
    if (min !== null && !Number.isNaN(min)) {
      items = items.filter((c) => Number(c.pump_score ?? c.score ?? 0) >= min);
    }
    if (symbolQuery.trim()) {
      const q = symbolQuery.trim().toUpperCase();
      items = items.filter((c) => String(c.symbol || "").toUpperCase().includes(q));
    }
    return items;
  }, [candidates, minScore, symbolQuery]);

  const action = async (fn: () => Promise<any>, successMsg: string) => {
    try {
      const res = await fn();
      setSnack({ open: true, msg: successMsg || JSON.stringify(res), severity: "success" });
      await load();
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Action failed"), severity: "error" });
    }
  };

  const candidateTs = (c: Candidate): number => {
    const v = c.detected_at_ms ?? c.timestamp_ms ?? c.created_at_ms ?? c.ts_ms ?? 0;
    const n = Number(v || 0);
    return Number.isFinite(n) ? n : 0;
  };

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Pump Center
      </Typography>
      <Typography variant="body2" sx={{ opacity: 0.8, mb: 2 }}>
        Pump-only controls via Gateway proxy (/api/mina/pump/*). No direct execution.
      </Typography>

      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }} flexWrap="wrap">
        <Button variant="outlined" onClick={() => void load()} disabled={loading}>
          Refresh
        </Button>
        <TextField
          select
          size="small"
          label="Status"
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          sx={{ minWidth: 160 }}
        >
          {STATUSES.map((s) => (
            <MenuItem key={s} value={s}>
              {s}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          size="small"
          label="Min Score"
          value={minScore}
          onChange={(e) => setMinScore(e.target.value)}
          sx={{ width: 140 }}
        />
        <TextField
          size="small"
          label="Symbol"
          value={symbolQuery}
          onChange={(e) => setSymbolQuery(e.target.value)}
          sx={{ width: 180 }}
        />
      </Stack>

      <Divider sx={{ my: 2 }} />

      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle1">Status</Typography>
        <Stack direction="row" spacing={2} sx={{ mt: 1, mb: 1 }} flexWrap="wrap">
          <Chip label={`Pump OK: ${String(status?.state?.last_heartbeat_ms ? "yes" : "no")}`} />
          <Chip label={`Counts: ${JSON.stringify(status?.counts || {})}`} />
        </Stack>
        <Box component="pre" sx={{ p: 2, background: "#0d1117", color: "#e6edf3", borderRadius: 1, fontSize: 12 }}>
          {JSON.stringify(status || {}, null, 2)}
        </Box>
      </Paper>

      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle1">Candidates</Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>ID</TableCell>
              <TableCell>Symbol</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Score</TableCell>
              <TableCell>Confidence</TableCell>
              <TableCell>Detected</TableCell>
              <TableCell>Label/Note</TableCell>
              <TableCell align="right">Actions</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filtered.map((c) => {
              const id = Number(c.id || 0);
              const note = noteById[id] ?? "";
              const label = labelById[id] ?? "PUMP";
              const side = sideById[id] ?? "LONG";
              const ts = candidateTs(c);
              return (
                <TableRow key={id || `${c.symbol}-${ts}`}>
                  <TableCell>{id || "—"}</TableCell>
                  <TableCell>{c.symbol || "—"}</TableCell>
                  <TableCell>{c.status || "—"}</TableCell>
                  <TableCell>{c.pump_score ?? c.score ?? "—"}</TableCell>
                  <TableCell>{c.ai_confidence ?? c.confidence ?? "—"}</TableCell>
                  <TableCell>{ts ? new Date(ts).toISOString() : "—"}</TableCell>
                  <TableCell>
                    <Stack direction="row" spacing={1}>
                      <TextField
                        size="small"
                        label="Label"
                        value={label}
                        onChange={(e) => setLabelById((p) => ({ ...p, [id]: e.target.value }))}
                        sx={{ width: 120 }}
                      />
                      <TextField
                        size="small"
                        label="Note"
                        value={note}
                        onChange={(e) => setNoteById((p) => ({ ...p, [id]: e.target.value }))}
                        sx={{ width: 180 }}
                      />
                    </Stack>
                  </TableCell>
                  <TableCell align="right">
                    <Stack direction="row" spacing={1} justifyContent="flex-end">
                      <Button size="small" onClick={() => action(() => approvePumpCandidate({ id, note }), "Approved")}>
                        Approve
                      </Button>
                      <Button size="small" onClick={() => action(() => rejectPumpCandidate({ id, note }), "Rejected")}>
                        Reject
                      </Button>
                      <TextField
                        select
                        size="small"
                        label="Side"
                        value={side}
                        onChange={(e) => setSideById((p) => ({ ...p, [id]: e.target.value }))}
                        sx={{ width: 100 }}
                      >
                        {SIDES.map((s) => (
                          <MenuItem key={s} value={s}>
                            {s}
                          </MenuItem>
                        ))}
                      </TextField>
                      <Button
                        size="small"
                        onClick={() => action(() => promotePumpCandidate({ id, side, note }), "Promoted")}
                      >
                        Promote
                      </Button>
                      <Button
                        size="small"
                        disabled={!c.symbol || !ts}
                        onClick={() =>
                          action(
                            () =>
                              setPumpLabel({
                                symbol: String(c.symbol || "").toUpperCase(),
                                timestamp_ms: ts,
                                label,
                                note,
                              }),
                            "Label saved"
                          )
                        }
                      >
                        Label
                      </Button>
                    </Stack>
                  </TableCell>
                </TableRow>
              );
            })}
            {filtered.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} sx={{ opacity: 0.7 }}>
                  {loading ? "Loading…" : "No candidates"}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Paper>

      <Paper sx={{ p: 2, mb: 2 }}>
        <Typography variant="subtitle1">Stats</Typography>
        <Box component="pre" sx={{ p: 2, background: "#0d1117", color: "#e6edf3", borderRadius: 1, fontSize: 12 }}>
          {JSON.stringify(stats || {}, null, 2)}
        </Box>
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Typography variant="subtitle1">Recent Trades</Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>ID</TableCell>
              <TableCell>Symbol</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>PNL</TableCell>
              <TableCell>Closed</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {trades.map((t) => (
              <TableRow key={t.id ?? t.trade_id ?? Math.random()}>
                <TableCell>{t.id ?? t.trade_id ?? "—"}</TableCell>
                <TableCell>{t.symbol ?? "—"}</TableCell>
                <TableCell>{t.status ?? "—"}</TableCell>
                <TableCell>{t.pnl ?? "—"}</TableCell>
                <TableCell>{t.closed_at ?? t.closed_at_ms ?? "—"}</TableCell>
              </TableRow>
            ))}
            {trades.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} sx={{ opacity: 0.7 }}>
                  {loading ? "Loading…" : "No trades"}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Paper>

      <Snackbar open={snack.open} autoHideDuration={4000} onClose={() => setSnack((s) => ({ ...s, open: false }))}>
        <Alert severity={snack.severity} onClose={() => setSnack((s) => ({ ...s, open: false }))} sx={{ width: "100%" }}>
          {snack.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
}
