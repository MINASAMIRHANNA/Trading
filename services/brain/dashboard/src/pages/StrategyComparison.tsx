import { useEffect, useState } from "react";
import {
  Paper,
  Typography,
  Table,
  TableRow,
  TableCell,
  TableHead,
  TableBody,
  Chip,
} from "@mui/material";
import { api } from "../api/client";

export default function StrategyComparison() {
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    api
      .get("/strategy-compare?symbol=BTCUSDT")
      .then((r) => setData(r.data));
  }, []);

  if (!data) return <Typography>Loading strategies…</Typography>;

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        Strategy Comparison
      </Typography>

      <Table>
        <TableHead>
          <TableRow>
            <TableCell>Strategy</TableCell>
            <TableCell>Trades</TableCell>
            <TableCell>Win Rate</TableCell>
            <TableCell>Expectancy</TableCell>
            <TableCell>Max DD</TableCell>
            <TableCell>Status</TableCell>
          </TableRow>
        </TableHead>

        <TableBody>
          {Object.entries(data).map(([name, s]: any) => {
            const good =
              s.expectancy > 0 && s.max_drawdown > -0.05;

            return (
              <TableRow key={name}>
                <TableCell>
                  <b>{name}</b>
                  <Typography variant="caption" display="block">
                    {s.description}
                  </Typography>
                </TableCell>
                <TableCell>{s.trades}</TableCell>
                <TableCell>
                  {(s.win_rate * 100).toFixed(1)}%
                </TableCell>
                <TableCell>
                  {s.expectancy.toFixed(5)}
                </TableCell>
                <TableCell>
                  {(s.max_drawdown * 100).toFixed(2)}%
                </TableCell>
                <TableCell>
                  {good ? (
                    <Chip label="VIABLE" color="success" />
                  ) : (
                    <Chip label="RISKY" color="warning" />
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
