import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Snackbar,
  Alert,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import {
  type UnifiedRole,
  fetchUnifiedSignals,
  approveUnifiedSignal,
  rejectUnifiedSignal,
  fetchUnifiedSignalDecision,
} from "../api/unified";
import KeyValueGrid from "../components/KeyValueGrid";
import { requestLiveGuard } from "../utils/liveGuard";

const StatusChip = ({ status }: { status: any }) => {
  const s = String(status || "UNKNOWN").toUpperCase();
  return <Chip size="small" label={s} />;
};

export default function MinaSignals() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [status, setStatus] = useState<string>("all");
  const [limit, setLimit] = useState<string>("30");
  const [loading, setLoading] = useState(false);
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [decisionLoading, setDecisionLoading] = useState(false);
  const [decisionData, setDecisionData] = useState<any>(null);
  const [decisionErr, setDecisionErr] = useState<string | null>(null);
  const [items, setItems] = useState<any[]>([]);
  const [snack, setSnack] = useState<{ open: boolean; msg: string; severity: "success" | "error" }>({
    open: false,
    msg: "",
    severity: "success",
  });

  const reload = async () => {
    setLoading(true);
    try {
      const data = await fetchUnifiedSignals(role, parseInt(limit || "30", 10), status);
      setItems(Array.isArray(data) ? data : []);
    } catch (e: any) {
      setItems([]);
      setSnack({ open: true, msg: String(e?.message || e || "Failed to load signals"), severity: "error" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role, status, limit]);

  const canAct = (it: any) => {
    const s = String(it?.status || "").toUpperCase();
    return s === "RECEIVED" || s === "PENDING" || s === "PENDING_APPROVAL";
  };

  const doApprove = async (it: any) => {
    const guard = role === "live" ? await requestLiveGuard(`Approve signal #${it?.id}`) : null;
    if (role === "live" && !guard) return;
    try {
      const r = await approveUnifiedSignal(role, Number(it.id), "Approved via Unified UI", undefined, guard || undefined);
      setSnack({ open: true, msg: `Approved signal #${it.id} (audit_id=${r?.audit_id ?? "?"})`, severity: "success" });
      await reload();
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Approve failed"), severity: "error" });
    }
  };

  const doReject = async (it: any) => {
    const guard = role === "live" ? await requestLiveGuard(`Reject signal #${it?.id}`) : null;
    if (role === "live" && !guard) return;
    try {
      const r = await rejectUnifiedSignal(role, Number(it.id), "rejected", "Rejected via Unified UI", guard || undefined);
      setSnack({ open: true, msg: `Rejected signal #${it.id} (audit_id=${r?.audit_id ?? "?"})`, severity: "success" });
      await reload();
    } catch (e: any) {
      setSnack({ open: true, msg: String(e?.message || e || "Reject failed"), severity: "error" });
    }
  };

  const onDecision = async (signalId: number) => {
    try {
      setDecisionErr(null);
      setDecisionData(null);
      setDecisionOpen(true);
      setDecisionLoading(true);
      const data = await fetchUnifiedSignalDecision(role, signalId);
      setDecisionData(data);
    } catch (e: any) {
      setDecisionErr(e?.message || "Failed to fetch decision");
    } finally {
      setDecisionLoading(false);
    }
  };

  const rows = useMemo(() => items || [], [items]);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Mina Signals
      </Typography>
      <Typography variant="body2" sx={{ opacity: 0.8, mb: 2 }}>
        Browse & approve/reject signals via Gateway → Dashboard (paper/live/pump).
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

        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel>Status</InputLabel>
          <Select label="Status" value={status} onChange={(e) => setStatus(String(e.target.value))}>
            <MenuItem value="all">all</MenuItem>
            <MenuItem value="RECEIVED">RECEIVED</MenuItem>
            <MenuItem value="PENDING_APPROVAL">PENDING_APPROVAL</MenuItem>
            <MenuItem value="APPROVED">APPROVED</MenuItem>
            <MenuItem value="REJECTED">REJECTED</MenuItem>
            <MenuItem value="EXECUTED">EXECUTED</MenuItem>
          </Select>
        </FormControl>

        <TextField size="small" label="Limit" value={limit} onChange={(e) => setLimit(e.target.value)} sx={{ width: 120 }} />
        <Button variant="contained" onClick={() => void reload()} disabled={loading}>
          Refresh
        </Button>
      </Box>

      {role === "live" ? (
        <Alert severity="warning" sx={{ mt: 2 }}>
          LIVE safety policy applies: double-confirm and optional PIN are required for write actions.
        </Alert>
      ) : null}

      <Divider sx={{ my: 2 }} />

      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>ID</TableCell>
            <TableCell>Time (UTC)</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Symbol</TableCell>
            <TableCell>Side</TableCell>
            <TableCell>TF</TableCell>
            <TableCell>Strategy</TableCell>
            <TableCell>Conf</TableCell>
            <TableCell>Note</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((it) => (
            <TableRow key={it.id}>
              <TableCell>{it.id}</TableCell>
              <TableCell>{it.received_at || it.created_at || "-"}</TableCell>
              <TableCell>
                <StatusChip status={it.status} />
              </TableCell>
              <TableCell>{it.symbol}</TableCell>
              <TableCell>{it.side}</TableCell>
              <TableCell>{it.timeframe}</TableCell>
              <TableCell>{it.strategy}</TableCell>
              <TableCell>{typeof it.confidence === "number" ? it.confidence.toFixed(2) : it.confidence ?? "-"}</TableCell>
              <TableCell sx={{ maxWidth: 280, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                {it.note || "-"}
              </TableCell>
              <TableCell align="right">
                <Button
                  size="small"
                  variant="text"
                  sx={{ mr: 1 }}
                  disabled={!it?.id || loading}
                  onClick={() => void onDecision(Number(it.id))}
                >
                  Decision
                </Button>
                <Button size="small" variant="outlined" sx={{ mr: 1 }} disabled={!canAct(it) || loading} onClick={() => void doApprove(it)}>
                  Approve
                </Button>
                <Button size="small" color="error" variant="outlined" disabled={!canAct(it) || loading} onClick={() => void doReject(it)}>
                  Reject
                </Button>
              </TableCell>
            </TableRow>
          ))}
          {rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={10} sx={{ opacity: 0.8 }}>
                {loading ? "Loading..." : "No signals."}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      
      <Dialog open={decisionOpen} onClose={() => setDecisionOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>Brain Decision</DialogTitle>
        <DialogContent>
          {decisionLoading ? (
            <Typography variant="body2">Loading…</Typography>
          ) : decisionErr ? (
            <Alert severity="error">{decisionErr}</Alert>
          ) : decisionData ? (
            <KeyValueGrid data={decisionData} />
          ) : (
            <Typography variant="body2">No data</Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDecisionOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>

      <Snackbar open={snack.open} autoHideDuration={4000} onClose={() => setSnack((s) => ({ ...s, open: false }))}>
        <Alert severity={snack.severity} onClose={() => setSnack((s) => ({ ...s, open: false }))} sx={{ width: "100%" }}>
          {snack.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
}
