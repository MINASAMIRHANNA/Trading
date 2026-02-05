import { useState } from "react";
import { Paper, TextField, Button, Typography, Stack, Box } from "@mui/material";
import { api } from "../api/client";

export default function AICoachChat() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(false);

  const presets = [
    "Best strategy now",
    "Why no trades",
    "Top incidents last hour",
    "Suggest safe settings changes",
  ];

  const ask = async (q?: string) => {
    const msg = (q ?? question).trim();
    if (!msg) return;
    setLoading(true);
    try {
      const res = await api.post("/ai_coach/chat", {
        question: msg,
      });
      setAnswer(res.data.answer);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6">AI Coach Chat</Typography>

      <Stack spacing={2} mt={2}>
        <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
          {presets.map((p) => (
            <Button key={p} variant="outlined" size="small" onClick={() => void ask(p)}>
              {p}
            </Button>
          ))}
        </Box>
        <TextField
          label="Ask about your trading performance"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          fullWidth
        />
        <Button variant="contained" onClick={() => void ask()} disabled={loading}>
          {loading ? "Thinking..." : "Ask AI Coach"}
        </Button>

        {answer && (
          <Paper sx={{ p: 2, backgroundColor: "#161b22" }}>
            <Typography>{answer}</Typography>
          </Paper>
        )}
      </Stack>
    </Paper>
  );
}
