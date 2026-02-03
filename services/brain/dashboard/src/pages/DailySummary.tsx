import { useEffect, useState } from "react";
import { Paper, Typography } from "@mui/material";
import { api } from "../api/client";

export default function DailySummary() {
  const [summary, setSummary] = useState<any>(null);

  useEffect(() => {
    api.get("/daily-summary?symbol=BTCUSDT").then((r) => setSummary(r.data));
  }, []);

  if (!summary) return <Typography>Loading daily summary…</Typography>;

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6">Daily Summary — {summary.date}</Typography>
      <Typography>Trades: {summary.trades}</Typography>
      <Typography>Win Rate: {(summary.win_rate * 100).toFixed(1)}%</Typography>
      <Typography>Expectancy: {summary.expectancy?.toFixed(5)}</Typography>
      <Typography>Best Regime: {summary.best_regime}</Typography>
      <Typography>Worst Regime: {summary.worst_regime}</Typography>
    </Paper>
  );
}
