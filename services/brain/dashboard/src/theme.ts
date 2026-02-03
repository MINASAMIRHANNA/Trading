import { createTheme } from "@mui/material/styles";

export const darkTheme = createTheme({
  palette: {
    mode: "dark",
    background: {
      default: "#0e1117",
      paper: "#161b22",
    },
    primary: {
      main: "#58a6ff",
    },
    secondary: {
      main: "#8b949e",
    },
  },
  typography: {
    fontFamily: "Inter, system-ui, sans-serif",
  },
});
