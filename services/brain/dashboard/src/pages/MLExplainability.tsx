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
import { fetchFeatureImportance } from "../api/ml";

type ImportanceRow = {
  feature: string;
  importance: number;
};

function humanize(feature: string) {
  return feature
    .replaceAll("_", " ")
    .replace("pct", "%")
    .replace("ema", "EMA")
    .toUpperCase();
}

export default function MLExplainability() {
  const [rows, setRows] = useState<ImportanceRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchFeatureImportance("BTCUSDT")
      .then((res) => {
        const list = Object.entries(res).map(([k, v]) => ({
          feature: k,
          importance: Number(v),
        }));

        if (!list.length) {
          setError("No ML importance data available");
        } else {
          setRows(
            list.sort(
              (a, b) => Math.abs(b.importance) - Math.abs(a.importance)
            )
          );
        }
      })
      .catch(() => setError("Failed to load ML importance"));
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
        ML Explainability — Feature Importance
      </Typography>

      <Table>
        <TableHead>
          <TableRow>
            <TableCell>Feature</TableCell>
            <TableCell align="right">Importance</TableCell>
            <TableCell align="center">Impact</TableCell>
          </TableRow>
        </TableHead>

        <TableBody>
          {rows.map((row, idx) => {
            const positive = row.importance > 0;
            return (
              <TableRow key={idx}>
                <TableCell>{humanize(row.feature)}</TableCell>
                <TableCell align="right">
                  {row.importance.toFixed(4)}
                </TableCell>
                <TableCell align="center">
                  {positive ? (
                    <Chip label="Positive" color="success" size="small" />
                  ) : (
                    <Chip label="Negative" color="error" size="small" />
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      <Typography
        variant="caption"
        sx={{ display: "block", mt: 2, opacity: 0.7 }}
      >
        Sorted by absolute importance. Positive = improves profitability.
      </Typography>
    </Paper>
  );
}
