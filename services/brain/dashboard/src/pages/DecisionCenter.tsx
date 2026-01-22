import ExecutionStatus from "../components/ExecutionStatus";
import DailyEducation from "../components/DailyEducation";
import { useEffect, useState } from "react";
import {
  Paper,
  Typography,
  Chip,
  Stack,
  Alert,
  Divider,
  Box,
  Button,
  Collapse,
} from "@mui/material";
import { api } from "../api/client";

export default function DecisionCenter() {
  const [data, setData] = useState<any>(null);
  const [showDetails, setShowDetails] = useState(false);

  useEffect(() => {
    api
      .get("/decision?symbol=BTCUSDT")
      .then((r) => setData(r.data))
      .catch(() =>
        setData({
          decision: "ERROR",
          warnings: ["Failed to load decision"],
        })
      );
  }, []);

  if (!data) {
    return <Typography>Loading decision…</Typography>;
  }

  const isTrade = data.decision === "TRADE_SELECTIVELY";

  return (
    <Paper sx={{ p: 4 }}>
      <Typography variant="h5" gutterBottom>
        Decision Center
      </Typography>

      <Stack spacing={2}>
        {/* Decision */}
        <Chip
          label={data.decision}
          color={isTrade ? "success" : "error"}
          sx={{ fontSize: 16, p: 1 }}
        />
        {/* 🔐 Execution Status */}
        <ExecutionStatus />
        {/* 📘 Daily Lesson */}
        <DailyEducation />

        {/* Strategy */}
        {data.recommended_strategy && (
          <Typography variant="h6">
            Strategy: {data.recommended_strategy}
          </Typography>
        )}

        {/* Confidence */}
        {data.confidence !== undefined && (
          <Typography>
            Confidence: {(data.confidence * 100).toFixed(0)}%
          </Typography>
        )}
        {data.data_progress !== undefined && ( 
          <Box>
            <Typography>
              Data Readiness: {(data.data_progress * 100).toFixed(0)}%
            </Typography>    

          <Box
             sx={{
               height: 8,
               backgroundColor: "#30363d",
               borderRadius: 4,
               overflow: "hidden",
            }}
          >
           <Box
             sx={{
               width: `${data.data_progress * 100}%`,
               height: "100%",
               backgroundColor: "#2ea043",  
            }}
          />
        </Box>
      </Box>
    )}
        {/* Warnings */}
        {data.warnings && data.warnings.length > 0 && (
          <Alert severity="warning">
            {data.warnings.map((w: string, i: number) => (
              <div key={i}>• {w}</div>
            ))}
          </Alert>
        )}
        
        {/* 📘 Daily Education */}
        <DailyEducation />

        <Divider />

        {/* Details Toggle */}
        {data.details && (
          <>
            <Button
              variant="outlined"
              onClick={() => setShowDetails(!showDetails)}
            >
              {showDetails ? "Hide Details" : "Show Strategy Details"}
            </Button>

            <Collapse in={showDetails}>
              <Box sx={{ mt: 2 }}>
                {Object.entries(data.details).map(
                  ([name, d]: any) => (
                    <Paper
                      key={name}
                      sx={{
                        p: 2,
                        mb: 1,
                        backgroundColor: "#161b22",
                      }}
                    >
                      <Typography variant="subtitle1">
                        {name}
                      </Typography>
                      <Typography variant="body2">
                        Trades: {d.metrics?.trades ?? "N/A"}
                      </Typography>
                      <Typography variant="body2">
                        Expectancy:{" "}
                        {d.metrics?.expectancy !== null &&
                         d.metrics?.expectancy !== undefined
                            ? d.metrics.expectancy.toFixed(5)
                            : "N/A"}
                      </Typography>
                      <Typography variant="body2">
                        Max Drawdown:{" "}
                        {d.metrics?.max_drawdown !== null &&
                         d.metrics?.max_drawdown !== undefined  
                          ? (d.metrics.max_drawdown * 100).toFixed(2) + "%"
                          : "N/A"}
                      </Typography>
                      <Typography variant="body2">
                        Score: {d.score}
                      </Typography>
                    </Paper>
                  )
                )}
              </Box>
            </Collapse>
          </>
        )}
      </Stack>
    </Paper>
  );
}
