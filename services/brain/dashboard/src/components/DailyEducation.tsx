import { useEffect, useState } from "react";
import {
  Paper,
  Typography,
  Alert,
} from "@mui/material";
import { api } from "../api/client";

export default function DailyEducation() {
  const [lesson, setLesson] = useState<any>(null);

  useEffect(() => {
    api
      .get("/daily-education/?symbol=BTCUSDT")
      .then((r) => setLesson(r.data))
      .catch(() =>
        setLesson({
          title: "Lesson unavailable",
          explanation: "Could not load today's lesson.",
          takeaway: "Try again later.",
        })
      );
  }, []);

  if (!lesson) return <Typography>Loading Daily Lesson…</Typography>;

  return (
    <Paper sx={{ p: 3 }}>
      <Typography variant="h6">📘 Daily Lesson</Typography>

      <Typography variant="subtitle1" sx={{ mt: 1 }}>
        {lesson.title}
      </Typography>

      <Typography sx={{ mt: 1 }}>
        {lesson.explanation}
      </Typography>

      <Alert severity="info" sx={{ mt: 2 }}>
        {lesson.takeaway}
      </Alert>
    </Paper>
  );
}
