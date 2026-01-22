import { useState } from "react";
import { Paper, TextField, Button, Typography, Stack } from "@mui/material";
import { api } from "../api/client";

export default function AICoachChat() {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");

  const ask = async () => {
    const res = await api.post("/ai-chat", {
      question,
      symbol: "BTCUSDT",
    });
    setAnswer(res.data.answer);
  };

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6">AI Coach Chat</Typography>

      <Stack spacing={2} mt={2}>
        <TextField
          label="Ask about your trading performance"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          fullWidth
        />
        <Button variant="contained" onClick={ask}>
          Ask AI Coach
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
