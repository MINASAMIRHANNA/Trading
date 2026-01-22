import { useState } from "react";
import {
  Paper,
  Typography,
  Button,
  Stack,
  FormControlLabel,
  Checkbox,
  Divider,
  Grid,
} from "@mui/material";
import { runSimulation } from "../api/simulate";

export default function Simulator() {
  const [onlyUptrend, setOnlyUptrend] = useState(true);
  const [counterTrend, setCounterTrend] = useState(true);
  const [result, setResult] = useState<any>(null);

  const handleSimulate = async () => {
    const payload = {
      symbol: "BTCUSDT",
      allowed_regimes: onlyUptrend ? [1.0] : undefined,
      allowed_alignment: counterTrend ? [-1.0] : undefined,
    };

    const res = await runSimulation(payload);
    setResult(res);
  };

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        What-If Simulator
      </Typography>

      <Stack spacing={1}>
        <FormControlLabel
          control={
            <Checkbox
              checked={onlyUptrend}
              onChange={(e) => setOnlyUptrend(e.target.checked)}
            />
          }
          label="Allow Uptrend Only"
        />

        <FormControlLabel
          control={
            <Checkbox
              checked={counterTrend}
              onChange={(e) => setCounterTrend(e.target.checked)}
            />
          }
          label="Allow Counter-Trend Only"
        />

        <Button variant="contained" onClick={handleSimulate}>
          Run Simulation
        </Button>
      </Stack>

      {result && (
        <>
          <Divider sx={{ my: 3 }} />
          <Grid container spacing={2}>
            <Metric title="Actual" data={result.actual} />
            <Metric title="Simulated" data={result.simulated} />
            <Metric title="Delta" data={result.delta} />
          </Grid>
        </>
      )}
    </Paper>
  );
}

function Metric({ title, data }: { title: string; data: any }) {
  return (
    <Grid item xs={12} md={4}>
      <Paper sx={{ p: 2 }}>
        <Typography variant="subtitle2">{title}</Typography>
        <Typography>Trades: {data.trades}</Typography>
        <Typography>
          Win Rate: {(data.win_rate * 100).toFixed(1)}%
        </Typography>
        <Typography>
          Expectancy: {data.expectancy.toFixed(5)}
        </Typography>
      </Paper>
    </Grid>
  );
}
