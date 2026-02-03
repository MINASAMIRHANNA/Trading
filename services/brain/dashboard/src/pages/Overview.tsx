import { useEffect, useState } from "react";
import { fetchOverview } from "../api/overview";
import Grid from "@mui/material/Grid";
import { Paper, Typography } from "@mui/material";

export default function Overview() {
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchOverview("BTCUSDT")
      .then(setData)
      .catch(() => setError("Failed to load overview"));
  }, []);

  if (error) return <Typography color="error">{error}</Typography>;
  if (!data) return <Typography>Loading overview...</Typography>;

  return (
    <Grid container spacing={2}>
      {["trades", "win_rate", "expectancy"].map((key) => (
        <Grid item xs={12} md={4} key={key}>
          <Paper sx={{ p: 2 }}>
            <Typography variant="subtitle2">{key.toUpperCase()}</Typography>
            <Typography variant="h4">
              {typeof data[key] === "number" ? data[key].toFixed(4) : data[key]}
            </Typography>
          </Paper>
        </Grid>
      ))}
    </Grid>
  );
}
