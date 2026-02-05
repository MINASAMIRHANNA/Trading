import { useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
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
  Paper,
} from "@mui/material";
import { type UnifiedRole, fetchUnifiedEquityHistory, fetchUnifiedPerfMetrics } from "../api/unified";

function parseTs(item: any): number {
  const cand = item?.timestamp_ms ?? item?.created_at_ms ?? item?.ts_ms ?? null;
  if (cand !== null && cand !== undefined && !Number.isNaN(Number(cand))) {
    return Number(cand);
  }
  const s = item?.timestamp ?? item?.created_at ?? item?.date_utc ?? item?.ts ?? null;
  if (s) {
    const t = Date.parse(String(s));
    if (!Number.isNaN(t)) return t;
  }
  return 0;
}

function LineChart({ points, height = 200 }: { points: { x: number; y: number }[]; height?: number }) {
  if (!points.length) {
    return <Typography sx={{ opacity: 0.7 }}>No data</Typography>;
  }
  const width = 720;
  const pad = 16;
  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  let minX = Math.min(...xs);
  let maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);

  if (minX === maxX) {
    minX = 0;
    maxX = points.length - 1;
  }

  const scaleX = (x: number, idx: number) => {
    const v = minX === maxX ? idx : (x - minX) / (maxX - minX);
    return pad + v * (width - pad * 2);
  };
  const scaleY = (y: number) => {
    const v = maxY === minY ? 0.5 : (y - minY) / (maxY - minY);
    return height - pad - v * (height - pad * 2);
  };

  const pts = points.map((p, i) => `${scaleX(p.x, i)},${scaleY(p.y)}`).join(" ");

  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
      <polyline fill="none" stroke="#4aa3ff" strokeWidth="2" points={pts} />
      <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} stroke="#2b3240" />
      <line x1={pad} y1={pad} x2={pad} y2={height - pad} stroke="#2b3240" />
    </svg>
  );
}

function pct(arr: number[], p: number): number {
  if (!arr.length) return 0;
  const sorted = [...arr].sort((a, b) => a - b);
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.floor((sorted.length - 1) * p)));
  return sorted[idx];
}

export default function Performance() {
  const [role, setRole] = useState<UnifiedRole>("paper");
  const [limit, setLimit] = useState("200");
  const [fromTs, setFromTs] = useState("");
  const [toTs, setToTs] = useState("");
  const [loading, setLoading] = useState(false);
  const [equity, setEquity] = useState<any[]>([]);
  const [perf, setPerf] = useState<any[]>([]);
  const [equityError, setEquityError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const params: any = { limit: parseInt(limit || "200", 10) };
      if (fromTs) params.from_ts = fromTs;
      if (toTs) params.to_ts = toTs;
      const [eq, pf] = await Promise.all([
        fetchUnifiedEquityHistory(role, params),
        fetchUnifiedPerfMetrics(role, params),
      ]);
      if (eq && eq.ok === false) {
        setEquity([]);
        setEquityError(String(eq.error || "equity_history_not_available"));
      } else {
        setEquity(Array.isArray(eq?.items) ? eq.items : []);
        setEquityError(null);
      }
      setPerf(Array.isArray(pf?.items) ? pf.items : []);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  const equityPoints = useMemo(() => {
    return equity
      .map((r, idx) => {
        const x = parseTs(r) || idx;
        const y = Number(r.total_balance ?? r.equity ?? 0) || 0;
        return { x, y };
      })
      .filter((p) => Number.isFinite(p.y));
  }, [equity]);

  const lastEquity = useMemo(() => {
    if (!equityPoints.length) return null;
    return equityPoints[equityPoints.length - 1].y;
  }, [equityPoints]);

  const perfStats = useMemo(() => {
    const durations = perf.map((r) => Number(r.duration_ms)).filter((n) => Number.isFinite(n));
    const byStage: Record<string, number[]> = {};
    const bySymbol: Record<string, number[]> = {};
    for (const r of perf) {
      const d = Number(r.duration_ms);
      if (!Number.isFinite(d)) continue;
      const stage = String(r.stage || "unknown");
      const sym = String(r.symbol || "?");
      (byStage[stage] ||= []).push(d);
      (bySymbol[sym] ||= []).push(d);
    }
    const stageRows = Object.entries(byStage).map(([stage, arr]) => ({
      stage,
      count: arr.length,
      avg: arr.reduce((a, b) => a + b, 0) / Math.max(1, arr.length),
      p95: pct(arr, 0.95),
    }));
    const symbolRows = Object.entries(bySymbol).map(([symbol, arr]) => ({
      symbol,
      count: arr.length,
      avg: arr.reduce((a, b) => a + b, 0) / Math.max(1, arr.length),
      p95: pct(arr, 0.95),
    }));
    stageRows.sort((a, b) => b.count - a.count);
    symbolRows.sort((a, b) => b.count - a.count);
    return {
      total: durations.length,
      avg: durations.reduce((a, b) => a + b, 0) / Math.max(1, durations.length),
      p95: pct(durations, 0.95),
      stageRows: stageRows.slice(0, 12),
      symbolRows: symbolRows.slice(0, 12),
    };
  }, [perf]);

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" sx={{ mb: 1 }}>
        Performance
      </Typography>
      <Typography variant="body2" sx={{ opacity: 0.8, mb: 2 }}>
        Equity curve and latency/perf metrics from mina_{role}.
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

        <TextField size="small" label="Limit" value={limit} onChange={(e) => setLimit(e.target.value)} sx={{ width: 120 }} />
        <TextField size="small" label="From (ts)" value={fromTs} onChange={(e) => setFromTs(e.target.value)} sx={{ minWidth: 180 }} />
        <TextField size="small" label="To (ts)" value={toTs} onChange={(e) => setToTs(e.target.value)} sx={{ minWidth: 180 }} />

        <Button variant="contained" onClick={() => void load()} disabled={loading}>
          Refresh
        </Button>
      </Box>

      <Divider sx={{ my: 2 }} />

      <Paper sx={{ p: 2, mb: 3 }}>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          Equity History
        </Typography>
        <Typography variant="body2" sx={{ opacity: 0.8, mb: 1 }}>
          Last equity: {lastEquity !== null ? lastEquity.toFixed(2) : "-"}
        </Typography>
        {equityError && (
          <Typography sx={{ mb: 1, color: "error.main" }}>
            {equityError}
          </Typography>
        )}
        <LineChart points={equityPoints} />
      </Paper>

      <Paper sx={{ p: 2 }}>
        <Typography variant="subtitle1" sx={{ mb: 1 }}>
          Performance Metrics
        </Typography>
        <Typography variant="body2" sx={{ opacity: 0.8, mb: 2 }}>
          Total events: {perfStats.total} · avg {perfStats.avg.toFixed(1)} ms · p95 {perfStats.p95.toFixed(1)} ms
        </Typography>

        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          By Stage
        </Typography>
        <Table size="small" sx={{ mb: 2 }}>
          <TableHead>
            <TableRow>
              <TableCell>Stage</TableCell>
              <TableCell>Count</TableCell>
              <TableCell>Avg (ms)</TableCell>
              <TableCell>P95 (ms)</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {perfStats.stageRows.map((r) => (
              <TableRow key={r.stage}>
                <TableCell>{r.stage}</TableCell>
                <TableCell>{r.count}</TableCell>
                <TableCell>{r.avg.toFixed(1)}</TableCell>
                <TableCell>{r.p95.toFixed(1)}</TableCell>
              </TableRow>
            ))}
            {perfStats.stageRows.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} sx={{ opacity: 0.7 }}>
                  No perf metrics.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>

        <Typography variant="subtitle2" sx={{ mb: 1 }}>
          By Symbol
        </Typography>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Symbol</TableCell>
              <TableCell>Count</TableCell>
              <TableCell>Avg (ms)</TableCell>
              <TableCell>P95 (ms)</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {perfStats.symbolRows.map((r) => (
              <TableRow key={r.symbol}>
                <TableCell>{r.symbol}</TableCell>
                <TableCell>{r.count}</TableCell>
                <TableCell>{r.avg.toFixed(1)}</TableCell>
                <TableCell>{r.p95.toFixed(1)}</TableCell>
              </TableRow>
            ))}
            {perfStats.symbolRows.length === 0 && (
              <TableRow>
                <TableCell colSpan={4} sx={{ opacity: 0.7 }}>
                  No perf metrics.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Paper>
    </Box>
  );
}
