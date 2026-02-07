import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "../../../tests/ui",
  testMatch: "unified_e2e.spec.ts",
  timeout: 240_000,
  expect: {
    timeout: 30_000,
  },
  use: {
    baseURL: process.env.UI_BASE_URL || "http://localhost:5173",
    headless: true,
    channel: "chrome",
    trace: "retain-on-failure",
  },
});
