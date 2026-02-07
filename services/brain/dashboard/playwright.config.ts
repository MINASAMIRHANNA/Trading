import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "../../../tests/ui",
  testMatch: "unified_buttons.spec.ts",
  timeout: 120_000,
  expect: {
    timeout: 20_000,
  },
  use: {
    baseURL: process.env.UI_BASE_URL || "http://localhost:5173",
    headless: true,
    channel: "chrome",
    trace: "retain-on-failure",
  },
});
