import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
  Button,
  TextField,
  Snackbar,
  Alert,
} from "@mui/material";
import { fetchAudit, replayAudit, type AuditItem } from "../api/audit";

function okChip(ok: boolean) {
  return (
    <Chip
      size="small"
      label={ok ? "OK" : "FAIL"}
      variant={ok ? "filled" : "outlined"}
    />
  );
}

export default function Audit() {
  const [snack, setSnack] = useState<{ open: boolean; msg: string; severity: "success" | "error" }>({ open: false, msg: "", severity: "success" });
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<AuditItem[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [role, setRole] = useState<string>("all");
  const [action, setAction] = useState<string>("all");
  const [q, setQ] = useState<string>("");
  const [traceId, setTraceId] = useState<string>("");

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchAudit(200);
      if (!res.ok) throw new Error(res.error || "audit_error");
      setItems(res.items || []);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const roles = useMemo(() => {
    const s = new Set<string>();
    items.forEach((it) => it.role && s.add(it.role));
    return Array.from(s).sort();
  }, [items]);

  const actions = useMemo(() => {
    const s = new Set<string>();
    items.forEach((it) => it.action && s.add(it.action));
    return Array.from(s).sort();
  }, [items]);

  const canReplay = (it: AuditItem) =>
    ["COMMAND_QUEUE", "SIGNAL_APPROVE", "SIGNAL_REJECT"].includes(String(it.action || "").toUpperCase());

  const doReplay = async (it: AuditItem) => {
    try {
      const res = await replayAudit(it.id);
      setSnack({ open: true, msg: `Replayed (${it.action}) → audit_id=${res?.audit_id ?? "?"}`, severity: "success" });
      await load();
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Replay failed"), severity: "error" });
    }
  };

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const traceNeedle = traceId.trim().toLowerCase();
    return items.filter((it) => {
      if (role !== "all" && (it.role || "") !== role) return false;
      if (action !== "all" && (it.action || "") !== action) return false;
      if (traceNeedle && !String(it.trace_id || "").toLowerCase().includes(traceNeedle)) return false;
      if (!needle) return true;
      const blob = JSON.stringify(it).toLowerCase();
      return blob.includes(needle);
    });
  }, [items, role, action, q, traceId]);

  return (
    <Box>
      <Typography variant="h4" sx={{ mb: 1 }}>
        Audit Log
      </Typography>
      <Typography sx={{ opacity: 0.8, mb: 2 }}>
        Latest actions recorded by the Gateway (approve/reject/commands) with trace IDs.
      </Typography>

      <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap", mb: 2 }}>
        <FormControl sx={{ minWidth: 180 }} size="small">
          <InputLabel>Role</InputLabel>
          <Select
            label="Role"
            value={role}
            onChange={(e: any) => setRole(e.target.value)}
          >
            <MenuItem value="all">All</MenuItem>
            {roles.map((r) => (
              <MenuItem key={r} value={r}>
                {r}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <FormControl sx={{ minWidth: 220 }} size="small">
          <InputLabel>Action</InputLabel>
          <Select
            label="Action"
            value={action}
            onChange={(e: any) => setAction(e.target.value)}
          >
            <MenuItem value="all">All</MenuItem>
            {actions.map((a) => (
              <MenuItem key={a} value={a}>
                {a}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <TextField
          size="small"
          label="Trace ID"
          value={traceId}
          onChange={(e) => setTraceId(e.target.value)}
          sx={{ minWidth: 220 }}
        />

        <TextField
          size="small"
          label="Search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          sx={{ minWidth: 260 }}
        />

        <Button variant="contained" onClick={load} disabled={loading}>
          {loading ? "Loading…" : "Refresh"}
        </Button>
      </Box>

      {error ? (
        <Box sx={{ p: 2, border: "1px solid #333", borderRadius: 2, mb: 2 }}>
          <Typography color="error">Error: {error}</Typography>
        </Box>
      ) : null}

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Time (UTC)</TableCell>
            <TableCell>OK</TableCell>
            <TableCell>Actor</TableCell>
            <TableCell>Action</TableCell>
            <TableCell>Role</TableCell>
            <TableCell>Target</TableCell>
            <TableCell>Trace</TableCell>
            <TableCell align="right">Replay</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {filtered.map((it) => (
            <TableRow key={it.id} hover>
              <TableCell sx={{ whiteSpace: "nowrap" }}>
                {it.ts_utc}
              </TableCell>
              <TableCell>{okChip(!!it.ok)}</TableCell>
              <TableCell>{it.actor}</TableCell>
              <TableCell>{it.action}</TableCell>
              <TableCell>{it.role || "-"}</TableCell>
              <TableCell sx={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {it.target_id || "-"}
              </TableCell>
              <TableCell sx={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {it.trace_id || "-"}
              </TableCell>
              <TableCell align="right">
                {canReplay(it) ? (
                  <Button size="small" variant="outlined" disabled={loading} onClick={() => void doReplay(it)}>
                    Replay
                  </Button>
                ) : (
                  <Typography sx={{ opacity: 0.5 }}>—</Typography>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>

      <Typography sx={{ mt: 2, opacity: 0.7 }}>
        Showing {filtered.length} / {items.length}
      </Typography>

      <Snackbar
        open={snack.open}
        autoHideDuration={4000}
        onClose={() => setSnack((s) => ({ ...s, open: false }))}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        <Alert severity={snack.severity} onClose={() => setSnack((s) => ({ ...s, open: false }))} sx={{ width: "100%" }}>
          {snack.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
}
