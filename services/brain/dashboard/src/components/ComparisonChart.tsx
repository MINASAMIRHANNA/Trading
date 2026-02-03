import { Paper, Typography } from "@mui/material";
import Plot from "react-plotly.js";

export default function ComparisonChart({
  actual,
  simulated,
}: {
  actual: any;
  simulated: any;
}) {
  return (
    <Paper sx={{ p: 2 }}>
      <Typography gutterBottom>Actual vs Simulated</Typography>

      <Plot
        data={[
          {
            x: ["Trades", "Win Rate", "Expectancy"],
            y: [actual.trades, actual.win_rate * 100, actual.expectancy],
            name: "Actual",
            type: "bar",
          },
          {
            x: ["Trades", "Win Rate", "Expectancy"],
            y: [
              simulated.trades,
              simulated.win_rate * 100,
              simulated.expectancy,
            ],
            name: "Simulated",
            type: "bar",
          },
        ]}
        layout={{
          barmode: "group",
          paper_bgcolor: "#161b22",
          plot_bgcolor: "#161b22",
          font: { color: "#e6edf3" },
          margin: { t: 20 },
        }}
        style={{ width: "100%", height: "300px" }}
      />
    </Paper>
  );
}
