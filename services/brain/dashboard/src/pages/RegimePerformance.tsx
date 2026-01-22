import { useEffect, useState } from "react";
import {
  Paper,
  Typography,
  Table,
  TableHead,
  TableRow,
  TableCell,
  TableBody,
  Chip,
} from "@mui/material";
import { fetchRegimePerformance } from "../api/performance";

type RegimeRow = {
  market_regime_encoded: number;
  trades: number;
  win_rate: number;
  avg_pnl: number;
};

export default function RegimePerformance() {
  const [data, setData] = useState<RegimeRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRegimePerformance("BTCUSDT")
      .then((res) => {
        if (!res || res.length === 0) {
          setError("No regime data available yet");
        } else {
          setData(res);
        }
      })
      .catch(() => setError("Failed to load regime performance"));
  }, []);

  if (error) {
    return (
      <Paper sx={{ p: 3 }}>
        <Typography color="error">{error}</Typography>
      </Paper>
    );
  }

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        Regime Performance
      </Typography>

      <Table>
        <TableHead>
          <TableRow>
            <TableCell>Market Regime</TableCell>
            <TableCell align="right">Trades</TableCell>
            <TableCell align="right">Win Rate</TableCell>
            <TableCell align="right">Avg PnL</TableCell>
            <TableCell align="center">Assessment</TableCell>
          </TableRow>
        </TableHead>

        <TableBody>
          {data.map((row, idx) => {
            const regime =
              row.market_regime_encoded === 1 ? "Uptrend" : "Downtrend";

            const isGood = row.avg_pnl > 0;

            return (
              <TableRow key={idx}>
                <TableCell>{regime}</TableCell>
                <TableCell align="right">{row.trades}</TableCell>
                <TableCell align="right">
                  {(row.win_rate * 100).toFixed(1)}%
                </TableCell>
                <TableCell align="right">
                  {row.avg_pnl.toFixed(6)}
                </TableCell>
                <TableCell align="center">
                  {isGood ? (
                    <Chip label="GOOD" color="success" size="small" />
                  ) : (
                    <Chip label="BAD" color="error" size="small" />
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </Paper>
  );
}
