import { useEffect, useState } from "react";
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
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { type UnifiedRole, fetchUnifiedPositions } from "../api/unified";

export default function MinaPositions() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [loading, setLoading] = useState(false);
  const [rows, setRows] = useState<any[]>([]);
  const [snack, setSnack] = useState<{ open: boolean; msg: string; severity: "success" | "error" }>({
    open: false,
    msg: "",
    severity: "success",
  });

  const reload = async () => {
    setLoading(true);
    try {
      const data = await fetchUnifiedPositions(role);
      const arr = Array.isArray(data) ? data : data?.positions || [];
      setRows(Array.isArray(arr) ? arr : []);
    } catch (e: any) {
      setRows([]);
      setSnack({ open: true, msg: String(e?.message || e || "Failed to load positions"), severity: "error" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Mina Positions
      </Typography>
      <Typography variant="body2" sx={{ opacity: 0.8, mb: 2 }}>
        Current positions snapshot from the selected dashboard role.
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

        <Button variant="contained" onClick={() => void reload()} disabled={loading}>
          Refresh
        </Button>
      </Box>

      <Divider sx={{ my: 2 }} />

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
          {rows.map((p, idx) => (
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
          {rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={7} sx={{ opacity: 0.8 }}>
                {loading ? "Loading..." : "No positions."}
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>

      <Snackbar open={snack.open} autoHideDuration={4000} onClose={() => setSnack((s) => ({ ...s, open: false }))}>
        <Alert severity={snack.severity} onClose={() => setSnack((s) => ({ ...s, open: false }))} sx={{ width: "100%" }}>
          {snack.msg}
        </Alert>
      </Snackbar>
    </Box>
  );
}
