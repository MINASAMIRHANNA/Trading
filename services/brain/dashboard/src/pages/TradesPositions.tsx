import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Dialog,
  DialogContent,
  DialogTitle,
  Divider,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { type UnifiedRole, fetchUnifiedPositions, fetchUnifiedTrades, fetchUnifiedTrade } from "../api/unified";
import KeyValueGrid from "../components/KeyValueGrid";

export default function TradesPositions() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [loading, setLoading] = useState(false);
  const [positions, setPositions] = useState<any[]>([]);
  const [trades, setTrades] = useState<any[]>([]);
  const [tradeStatus, setTradeStatus] = useState<string>("all");
  const [tradeLimit, setTradeLimit] = useState<string>("50");

  const [detailOpen, setDetailOpen] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailData, setDetailData] = useState<any>(null);

  const reload = async () => {
    setLoading(true);
    try {
      const [pos, tradeRes] = await Promise.all([
        fetchUnifiedPositions(role),
        fetchUnifiedTrades(role, parseInt(tradeLimit || "50", 10), tradeStatus),
      ]);
      const arr = Array.isArray(pos) ? pos : pos?.positions || [];
      setPositions(Array.isArray(arr) ? arr : []);
      const titems = (tradeRes && (tradeRes.items || tradeRes)) || [];
      setTrades(Array.isArray(titems) ? titems : []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role, tradeStatus, tradeLimit]);

  const openTrade = async (t: any) => {
    const tid = t?.id ?? t?.trade_id ?? null;
    setDetailOpen(true);
    setDetailLoading(true);
    setDetailError(null);
    try {
      if (tid === null || tid === undefined) {
        setDetailData(t);
        return;
      }
      const res = await fetchUnifiedTrade(role, Number(tid));
      setDetailData(res?.item ?? res ?? t);
    } catch (e: any) {
      setDetailError(e?.message || "Failed to load trade details");
      setDetailData(t);
    } finally {
      setDetailLoading(false);
    }
  };

  const tradeRows = useMemo(() => trades || [], [trades]);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Trades & Positions
      </Typography>
      <Typography variant="body2" sx={{ opacity: 0.8, mb: 2 }}>
        Positions come from dashboard snapshots. Trades are read from mina_{"<role>"}.trades via Gateway.
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

        <FormControl size="small" sx={{ minWidth: 160 }}>
          <InputLabel>Status</InputLabel>
          <Select label="Status" value={tradeStatus} onChange={(e) => setTradeStatus(String(e.target.value))}>
            <MenuItem value="all">all</MenuItem>
            <MenuItem value="open">OPEN</MenuItem>
            <MenuItem value="closed">CLOSED</MenuItem>
          </Select>
        </FormControl>

        <TextField
          size="small"
          label="Limit"
          value={tradeLimit}
          onChange={(e) => setTradeLimit(e.target.value)}
          sx={{ width: 120 }}
        />

        <Button variant="contained" onClick={() => void reload()} disabled={loading}>
          Refresh
        </Button>
      </Box>

      <Divider sx={{ my: 2 }} />

      <Typography variant="h6" sx={{ mb: 1 }}>
        Positions
      </Typography>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>Symbol</TableCell>
            <TableCell>Side</TableCell>
            <TableCell>Qty</TableCell>
            <TableCell>Entry</TableCell>
            <TableCell>Mark</TableCell>
            <TableCell>PNL</TableCell>
            <TableCell>Status</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {positions.map((p, idx) => (
            <TableRow key={idx}>
              <TableCell>{p.symbol ?? p.pair ?? "-"}</TableCell>
              <TableCell>{p.side ?? p.position_side ?? "-"}</TableCell>
              <TableCell>{p.qty ?? p.quantity ?? "-"}</TableCell>
              <TableCell>{p.entry_price ?? "-"}</TableCell>
              <TableCell>{p.mark_price ?? p.price ?? "-"}</TableCell>
              <TableCell>{p.pnl ?? p.unrealized_pnl ?? "-"}</TableCell>
              <TableCell>{p.status ?? "-"}</TableCell>
            </TableRow>
          ))}
          {positions.length === 0 && (
            <TableRow>
              <TableCell colSpan={7} sx={{ opacity: 0.8 }}>
                {loading ? "Loading..." : "No positions."}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <Divider sx={{ my: 2 }} />

      <Typography variant="h6" sx={{ mb: 1 }}>
        Trades
      </Typography>
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>ID</TableCell>
            <TableCell>Symbol</TableCell>
            <TableCell>Status</TableCell>
            <TableCell>Side</TableCell>
            <TableCell>PNL</TableCell>
            <TableCell>Closed/Time</TableCell>
            <TableCell align="right">Actions</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {tradeRows.map((t, idx) => {
            const tid = t?.id ?? t?.trade_id ?? idx;
            return (
              <TableRow key={tid}>
                <TableCell>{t?.id ?? t?.trade_id ?? "-"}</TableCell>
                <TableCell>{t?.symbol ?? t?.pair ?? "-"}</TableCell>
                <TableCell>{t?.status ?? "-"}</TableCell>
                <TableCell>{t?.side ?? t?.signal ?? "-"}</TableCell>
                <TableCell>{t?.pnl ?? "-"}</TableCell>
                <TableCell>{t?.closed_at_ms ?? t?.closed_at ?? t?.updated_at ?? t?.timestamp ?? "-"}</TableCell>
                <TableCell align="right">
                  <Button size="small" onClick={() => void openTrade(t)}>
                    View
                  </Button>
                </TableCell>
              </TableRow>
            );
          })}
          {tradeRows.length === 0 && (
            <TableRow>
              <TableCell colSpan={7} sx={{ opacity: 0.8 }}>
                {loading ? "Loading..." : "No trades."}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <Dialog open={detailOpen} onClose={() => setDetailOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>Trade Details</DialogTitle>
        <DialogContent>
          {detailLoading && <Typography sx={{ mb: 1 }}>Loading…</Typography>}
          {detailError && (
            <Typography sx={{ mb: 1, color: "error.main" }}>
              {detailError}
            </Typography>
          )}
          <KeyValueGrid data={detailData} />
        </DialogContent>
      </Dialog>
    </Box>
  );
}
