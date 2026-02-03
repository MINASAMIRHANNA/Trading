import React from "react";
import { Box, Paper, Typography } from "@mui/material";

type Props = { children: React.ReactNode };
type State = { error: any };

export class ErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error: any) {
    return { error };
  }

  componentDidCatch(error: any, info: any) {
    // eslint-disable-next-line no-console
    console.error("UI crashed:", error, info);
  }

  render() {
    if (this.state.error) {
      const err = this.state.error;
      const details = String(err?.stack || err?.message || err);

      return (
        <Box sx={{ p: 4 }}>
          <Paper sx={{ p: 2, border: "1px solid rgba(255,0,0,0.25)" }}>
            <Typography variant="h6" color="error">
              UI crashed
            </Typography>
            <Typography sx={{ opacity: 0.8, mt: 1 }}>
              Open DevTools Console for details.
            </Typography>

            <Box
              component="pre"
              sx={{
                mt: 2,
                p: 2,
                overflowX: "auto",
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                fontSize: 12,
                borderRadius: 1,
                backgroundColor: "rgba(255,255,255,0.04)",
              }}
            >
              {details}
            </Box>
          </Paper>
        </Box>
      );
    }

    return this.props.children;
  }
}
