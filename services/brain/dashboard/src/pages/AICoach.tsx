import { useEffect, useState } from "react";
import {
  Paper,
  Typography,
  List,
  ListItem,
} from "@mui/material";
import { api } from "../api/client";

export default function AICoach() {
  const [coach, setCoach] = useState<any>(null);

  useEffect(() => {
    api
      .get("/ai-coach?symbol=BTCUSDT")
      .then((r) => setCoach(r.data))
      .catch(() => setCoach({ advice: ["Failed to load AI Coach"] }));
  }, []);

  if (!coach) return <Typography>Loading AI Coach…</Typography>;

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6" gutterBottom>
        🤖 AI Coach — Daily Advice
      </Typography>

      <List>
        {coach.advice?.map((a: string, i: number) => (
          <ListItem key={i}>• {a}</ListItem>
        ))}
      </List>
    </Paper>
  );
}









