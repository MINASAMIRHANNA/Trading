import { useEffect, useState } from "react";
import Plot from "react-plotly.js";
import { fetchFeatureImportance } from "../api/ml";
import { Paper, Typography } from "@mui/material";

export default function MLExplain() {
  const [data, setData] = useState<any>({});

  useEffect(() => {
    fetchFeatureImportance("BTCUSDT").then(setData);
  }, []);

  const features = Object.keys(data);
  const values = Object.values(data);

  if (!features.length) return <Typography>Loading...</Typography>;

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        ML Feature Importance
      </Typography>

      <Plot
        data={[
          {
            x: features,
            y: values,
            type: "bar",
          },
        ]}
        layout={{
          title: "Feature Importance",
          paper_bgcolor: "#161b22",
          plot_bgcolor: "#161b22",
          font: { color: "#e6edf3" },
        }}
        style={{ width: "100%", height: "400px" }}
      />
    </Paper>
  );
}
