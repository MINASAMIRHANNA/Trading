import { Box, Paper, Typography } from "@mui/material";

type Value = string | number | boolean | null | undefined | Record<string, unknown> | unknown[];

function formatValue(v: Value): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return Number.isFinite(v) ? v.toFixed(2).replace(/\.00$/, "") : String(v);
  if (typeof v === "boolean") return v ? "true" : "false";
  if (Array.isArray(v)) return `[${v.length} items]`;
  if (typeof v === "object") return "object";
  return String(v);
}

export default function KeyValueGrid({
  data,
  columns = 4,
  titleMap = {},
}: {
  data: Record<string, Value> | null | undefined;
  columns?: number;
  titleMap?: Record<string, string>;
}) {
  const entries = Object.entries(data || {});
  if (!entries.length) {
    return <Typography variant="body2">No data</Typography>;
  }
  const cols = Math.max(1, Math.min(columns, 6));
  return (
    <Box
      sx={{
        display: "grid",
        gap: 2,
        gridTemplateColumns: `repeat(auto-fit, minmax(${Math.floor(900 / cols)}px, 1fr))`,
      }}
    >
      {entries.map(([k, v]) => (
        <Paper key={k} sx={{ p: 2, background: "#0b1220" }}>
          <Typography variant="caption" sx={{ opacity: 0.7 }}>
            {titleMap[k] || k}
          </Typography>
          <Typography variant="h6" sx={{ mt: 0.5 }}>
            {formatValue(v)}
          </Typography>
        </Paper>
      ))}
    </Box>
  );
}
