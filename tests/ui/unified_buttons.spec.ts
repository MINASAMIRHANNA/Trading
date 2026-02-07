import { expect, test } from "../../services/brain/dashboard/node_modules/@playwright/test";

function setupDialogAutoAccept(page: any) {
  page.on("dialog", async (dialog: any) => {
    const msg = String(dialog.message() || "");
    if (dialog.type() === "prompt") {
      if (msg.toLowerCase().includes("type live")) {
        await dialog.accept("LIVE");
        return;
      }
      if (msg.toLowerCase().includes("pin")) {
        await dialog.accept("0000");
        return;
      }
      await dialog.accept("ui_test");
      return;
    }
    await dialog.accept();
  });
}

async function assertUiActionLogged(request: any, params: Record<string, string>) {
  const q = new URLSearchParams(params);
  await expect
    .poll(async () => {
      const res = await request.get(`/api/ops/ui_actions?limit=20&${q.toString()}`);
      if (!res.ok()) return 0;
      const body = await res.json();
      return Number(body?.count || 0);
    })
    .toBeGreaterThan(0);
}

test.describe.configure({ mode: "serial" });

test("Ops controls write through gateway and produce audit rows", async ({ page, request }) => {
  setupDialogAutoAccept(page);
  await page.goto("/ops-live");
  await page.getByTestId("ops-role").selectOption("paper");

  const waitCommand = page.waitForResponse((res) => res.url().includes("/api/ops/command") && res.request().method() === "POST");
  await page.getByTestId("ops-restart-bot").click();
  const cmdResponse = await waitCommand;
  expect(cmdResponse.ok()).toBeTruthy();
  const cmdBody = await cmdResponse.json();
  expect(cmdBody?.ok).toBeTruthy();

  await assertUiActionLogged(request, { trace_id: String(cmdBody?.trace_id || "") });
});

test("Manual execution creates command/trade side effects and ui audit", async ({ page, request }) => {
  setupDialogAutoAccept(page);
  await page.goto("/manual-execution");
  await page.getByTestId("manual-exec-symbol").fill("BTCUSDT");
  await page.getByTestId("manual-exec-amount").fill("120");
  await page.getByTestId("manual-exec-market").selectOption("futures");
  await page.getByTestId("manual-exec-direction").selectOption("LONG");

  const waitExec = page.waitForResponse((res) => res.url().includes("/api/manual/execute") && res.request().method() === "POST");
  await page.getByTestId("manual-exec-submit").click();
  const execResponse = await waitExec;
  expect(execResponse.ok()).toBeTruthy();
  const execBody = await execResponse.json();
  expect(execBody?.ok).toBeTruthy();
  expect(Number(execBody?.command_id || 0)).toBeGreaterThan(0);
  expect(String(execBody?.trace_id || "").length).toBeGreaterThan(8);

  await expect
    .poll(async () => {
      const res = await request.get("/api/unified/paper/commands/history?limit=100");
      if (!res.ok()) return false;
      const body = await res.json();
      const items = Array.isArray(body?.items) ? body.items : [];
      return items.some((row: any) => Number(row?.id || 0) === Number(execBody.command_id));
    })
    .toBeTruthy();

  if (Number(execBody?.trade_id || 0) > 0) {
    await expect
      .poll(async () => {
        const res = await request.get("/api/unified/paper/trades?limit=100");
        if (!res.ok()) return false;
        const body = await res.json();
        const items = Array.isArray(body?.items) ? body.items : [];
        return items.some((row: any) => Number(row?.id || 0) === Number(execBody.trade_id));
      })
      .toBeTruthy();
  }

  await assertUiActionLogged(request, { trace_id: String(execBody.trace_id) });
});

test("Historical snapshot POST returns indicators and logs ui action", async ({ page, request }) => {
  setupDialogAutoAccept(page);
  await page.goto("/historical-snapshot-utc");
  await page.getByTestId("snapshot-symbol").fill("SOLUSDT");
  await page.getByTestId("snapshot-market").selectOption("futures");
  await page.getByTestId("snapshot-interval").selectOption("5m");
  await page.getByTestId("snapshot-at-local").fill("2026-02-06T14:30");

  const waitSnapshot = page.waitForResponse((res) => res.url().includes("/api/snapshot") && res.request().method() === "POST");
  await page.getByTestId("snapshot-run").click();
  const snapResponse = await waitSnapshot;
  expect(snapResponse.ok()).toBeTruthy();
  const snapBody = await snapResponse.json();
  expect(snapBody?.ok).toBeTruthy();
  expect(snapBody?.indicators).toBeTruthy();
  expect(snapBody?.candle).toBeTruthy();

  await assertUiActionLogged(request, { trace_id: String(snapBody?.trace_id || "") });
});

test("Brain inspector traces alias works and browser uses only /api gateway calls", async ({ page }) => {
  const blockedHosts: string[] = [];
  page.on("request", (req) => {
    const url = req.url();
    if (url.includes(":8100") || url.includes(":8000") || url.includes(":8001") || url.includes(":8002")) {
      blockedHosts.push(url);
    }
  });

  await page.goto("/live-brain-inspector");
  const waitTrace = page.waitForResponse((res) => res.url().includes("/api/brain/inspector/traces") || res.url().includes("/api/brain/inspector/decision_traces"));
  await page.getByTestId("inspector-refresh").click();
  const traceResponse = await waitTrace;
  expect(traceResponse.status()).toBeLessThan(500);
  expect(blockedHosts).toEqual([]);
});
