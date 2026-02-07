import { createTheme } from "@mui/material/styles";

export const darkTheme = createTheme({
  palette: {
    mode: "dark",
    background: {
      default: "#0b0e14",
      paper: "#161b22",
    },
    primary: {
      main: "#1f6feb",
    },
    secondary: {
      main: "#8b949e",
    },
    success: {
      main: "#2ea043",
    },
    error: {
      main: "#da3633",
    },
    warning: {
      main: "#d29922",
    },
  },
  typography: {
    fontFamily: "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
    fontSize: 13,
  },
  shape: {
    borderRadius: 8,
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: "#0b0e14",
          color: "#e6edf3",
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          border: "1px solid #30363d",
          backgroundColor: "#161b22",
        },
      },
    },
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: "none",
          fontWeight: 700,
        },
      },
    },
  },
});
