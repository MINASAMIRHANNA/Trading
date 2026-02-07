import { useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Divider,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { api } from "../api/client";
import KeyValueGrid from "../components/KeyValueGrid";

export default function DecisionCenter() {
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [role, setRole] = useState<"paper" | "live" | "pump">("paper");
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [timeframe, setTimeframe] = useState("1m");
  const [note, setNote] = useState("brain suggestion (shadow)");

  const [loadingDecision, setLoadingDecision] = useState(false);
  const [decision, setDecision] = useState<any>(null);
  const [decisionError, setDecisionError] = useState<string>("");

  const [staging, setStaging] = useState(false);
  const [stageResult, setStageResult] = useState<any>(null);
  const [stageError, setStageError] = useState<string>("");

  const loadDecision = async () => {
    setLoadingDecision(true);
    setDecisionError("");
    try {
      const res = await api.get("/decision", { params: { symbol: symbol.trim().toUpperCase() } });
      setDecision(res.data);
    } catch (e: any) {
      setDecision(null);
      setDecisionError(e?.response?.data?.detail || e?.message || "Failed to load decision");
    } finally {
      setLoadingDecision(false);
    }
  };

  const stageSignal = async () => {
    setStaging(true);
    setStageError("");
    setStageResult(null);
    try {
      const url = `/unified/${role}/signals/suggest_from_decision?symbol=${encodeURIComponent(
        symbol.trim().toUpperCase()
      )}`;
      const res = await api.post(url, {
        side,
        timeframe: timeframe.trim() || "1m",
        note: note.trim(),
      });
      setStageResult(res.data);
    } catch (e: any) {
      setStageError(e?.response?.data?.detail || e?.response?.data?.reason || e?.message || "Failed to stage signal");
    } finally {
      setStaging(false);
    }
  };

  useEffect(() => {
    loadDecision();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 2 }}>
        Decision Center
      </Typography>

      <Card>
        <CardContent>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 2 }}>
            <TextField
              size="small"
              label="Symbol"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value)}
              placeholder="BTCUSDT"
              sx={{ minWidth: 140 }}
            />
            <Button variant="contained" onClick={loadDecision} disabled={loadingDecision || !symbol.trim()}>
              {loadingDecision ? "Loading..." : "Refresh decision"}
            </Button>
            <Box sx={{ flex: 1 }} />
            <TextField
              size="small"
              select
              label="Stage to role"
              value={role}
              onChange={(e) => setRole(e.target.value as any)}
              sx={{ minWidth: 140 }}
            >
              <MenuItem value="paper">paper</MenuItem>
              <MenuItem value="live">live</MenuItem>
              <MenuItem value="pump">pump</MenuItem>
            </TextField>
            <TextField
              size="small"
              select
              label="Side"
              value={side}
              onChange={(e) => setSide(e.target.value as any)}
              sx={{ minWidth: 120 }}
            >
              <MenuItem value="BUY">BUY</MenuItem>
              <MenuItem value="SELL">SELL</MenuItem>
            </TextField>
            <TextField
              size="small"
              label="Timeframe"
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value)}
              sx={{ minWidth: 120 }}
            />
          </Stack>

          <TextField
            size="small"
            label="Note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            fullWidth
            sx={{ mb: 2 }}
          />

          {decisionError ? <Alert severity="error" sx={{ mb: 2 }}>{decisionError}</Alert> : null}

          <Typography variant="subtitle1" sx={{ mb: 1 }}>
            Brain decision (via Gateway /api/decision)
          </Typography>
          {decision ? (
            <KeyValueGrid data={decision} />
          ) : (
            <Typography variant="body2">{loadingDecision ? "Loading..." : "No decision yet"}</Typography>
          )}

          <Divider sx={{ my: 2 }} />

          <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }}>
            <Typography variant="subtitle1" sx={{ flex: 1 }}>
              Shadow action: stage a Mina inbox signal (no approve / no execution)
            </Typography>
            <Button variant="outlined" onClick={stageSignal} disabled={staging || !symbol.trim()}>
              {staging ? "Staging..." : "Stage signal"}
            </Button>
          </Stack>

          {stageError ? <Alert severity="error" sx={{ mt: 2 }}>{stageError}</Alert> : null}
          {stageResult ? (
            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Stage result
              </Typography>
              <KeyValueGrid data={stageResult} />
            </Box>
          ) : null}
        </CardContent>
      </Card>
    </Box>
  );
}
