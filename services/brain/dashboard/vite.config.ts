import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(() => {
  const apiKey = process.env.VITE_API_KEY || "";

  return {
    plugins: [react()],
    server: {
      // Local dev defaults (override in Docker via env)
      host: process.env.VITE_HOST || "127.0.0.1",
      port: Number(process.env.VITE_PORT || 5173),
      proxy: {
        "/api": {
          // In Docker, use: VITE_PROXY_TARGET=http://gateway_api:8200
          target: process.env.VITE_PROXY_TARGET || "http://127.0.0.1:8200",
          changeOrigin: true,
          ...(apiKey
            ? { headers: { "X-API-Key": apiKey } }
            : {}),
        },
      },
    },
  };
});
