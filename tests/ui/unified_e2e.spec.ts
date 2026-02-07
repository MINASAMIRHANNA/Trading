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
      await dialog.accept("ui_e2e");
      return;
    }
    await dialog.accept();
  });
}

test.describe.configure({ mode: "serial" });

test("Unified Dashboard control plane works end-to-end", async ({ page, request }) => {
  setupDialogAutoAccept(page);

  const directUpstreamCalls: string[] = [];
  page.on("request", (req: any) => {
    const url = String(req.url() || "");
    if (url.includes(":8100") || url.includes(":8000") || url.includes(":8001") || url.includes(":8002")) {
      directUpstreamCalls.push(url);
    }
  });

  // 1) Signals (paper) inbox shows pending + approve flow changes status.
  const pendingRes = await request.get("/api/unified/paper/signals?status=PENDING_APPROVAL&limit=100");
  expect(pendingRes.ok()).toBeTruthy();
  const pendingBody = await pendingRes.json();
  const pendingItems = Array.isArray(pendingBody?.items) ? pendingBody.items : [];
  expect(pendingItems.length).toBeGreaterThan(0);
  const signalId = Number(pendingItems[0]?.id || 0);
  expect(signalId).toBeGreaterThan(0);

  await page.goto("/signals");
  await page.getByTestId("signals-role").selectOption("paper");
  await page.getByTestId("signals-tab-inbox").click();
  await page.getByTestId("signals-refresh").click();
  await expect(page.getByTestId(`signal-id-${signalId}`)).toBeVisible();

  const approveResponseWaiter = page.waitForResponse(
    (res: any) =>
      res.url().includes(`/api/unified/paper/signals/${signalId}/approve`) && res.request().method() === "POST",
  );
  await page.getByTestId(`signals-approve-${signalId}`).click();
  const approveResponse = await approveResponseWaiter;
  expect(approveResponse.ok()).toBeTruthy();

  await expect
    .poll(async () => {
      const res = await request.get(`/api/unified/paper/signals/${signalId}`);
      if (!res.ok()) return "";
      const body = await res.json();
      return String(body?.item?.status || body?.status || "");
    })
    .not.toBe("PENDING_APPROVAL");

  // 2) Manual execution works and creates side effects.
  await page.goto("/manual-execution");
  await page.getByTestId("manual-exec-symbol").fill("BTCUSDT");
  await page.getByTestId("manual-exec-amount").fill("120");
  await page.getByTestId("manual-exec-market").selectOption("futures");
  await page.getByTestId("manual-exec-direction").selectOption("LONG");

  const manualResponseWaiter = page.waitForResponse(
    (res: any) => res.url().includes("/api/manual/execute") && res.request().method() === "POST",
  );
  await page.getByTestId("manual-exec-submit").click();
  const manualResponse = await manualResponseWaiter;
  expect(manualResponse.ok()).toBeTruthy();
  const manualBody = await manualResponse.json();
  expect(manualBody?.ok).toBeTruthy();

  const manualTradeId = Number(manualBody?.trade_id || 0);
  if (manualTradeId > 0) {
    await expect
      .poll(async () => {
        const res = await request.get("/api/unified/paper/trades?limit=100");
        if (!res.ok()) return false;
        const body = await res.json();
        const items = Array.isArray(body?.items) ? body.items : [];
        return items.some((x: any) => Number(x?.id || 0) === manualTradeId);
      })
      .toBeTruthy();
  }

  // 3) Trades page is live after actions.
  await page.goto("/trades-positions");
  await page.getByTestId("trades-refresh").click();
  await expect(page.getByRole("heading", { name: "Trades", exact: true })).toBeVisible();
  const firstTradeView = page.locator('[data-testid^="trade-view-"]').first();
  if ((await firstTradeView.count()) > 0) {
    await firstTradeView.click();
    await expect(page.getByText("Trade Details", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
  }

  // 4) Snapshot page (UTC) flow.
  await page.goto("/historical-snapshot-utc");
  await page.getByTestId("snapshot-symbol").fill("SOLUSDT");
  await page.getByTestId("snapshot-market").selectOption("futures");
  await page.getByTestId("snapshot-interval").selectOption("5m");
  await page.getByTestId("snapshot-at-local").fill("2026-02-06T14:30");
  const snapshotWaiter = page.waitForResponse(
    (res: any) => res.url().includes("/api/snapshot") && res.request().method() === "POST",
  );
  await page.getByTestId("snapshot-run").click();
  const snapshotResponse = await snapshotWaiter;
  expect(snapshotResponse.ok()).toBeTruthy();

  // 5) Teach AI actions.
  await page.goto("/teach-ai");
  await page.getByTestId("learn-role").selectOption("paper");

  const trainWaiter = page.waitForResponse((res: any) => res.url().includes("/api/learn/train") && res.request().method() === "POST");
  await page.getByTestId("learn-train").click();
  const trainResponse = await trainWaiter;
  expect(trainResponse.status()).toBeLessThan(500);

  const promoteWaiter = page.waitForResponse((res: any) => res.url().includes("/api/learn/promote") && res.request().method() === "POST");
  await page.getByTestId("learn-promote").click();
  const promoteResponse = await promoteWaiter;
  expect(promoteResponse.status()).toBeLessThan(500);

  const rollbackWaiter = page.waitForResponse((res: any) => res.url().includes("/api/learn/rollback") && res.request().method() === "POST");
  await page.getByTestId("learn-rollback").click();
  const rollbackResponse = await rollbackWaiter;
  expect(rollbackResponse.status()).toBeLessThan(500);

  // 6) Notifications save/test.
  await page.goto("/alerts");
  await page.getByTestId("alerts-enabled").check();

  const saveWaiter = page.waitForResponse((res: any) => res.url().includes("/api/notifications/settings") && res.request().method() === "POST");
  await page.getByTestId("alerts-save").click();
  const saveResponse = await saveWaiter;
  expect(saveResponse.status()).toBeLessThan(500);

  const testWaiter = page.waitForResponse((res: any) => res.url().includes("/api/notifications/test") && res.request().method() === "POST");
  await page.getByTestId("alerts-test").click();
  const notifTestResponse = await testWaiter;
  expect(notifTestResponse.status()).toBeLessThan(500);

  // 7) Status/Doctor checks view.
  await page.goto("/status-maintenance");
  await page.getByTestId("status-refresh").click();
  await expect(page.getByText("pump_hunter.py confirmed", { exact: true })).toBeVisible();
  await page.getByTestId("status-tab-doctor").click();
  await expect(page.getByTestId("doctor-run-quick")).toBeVisible();
  const doctorQuickWaiter = page.waitForResponse(
    (res: any) => res.url().includes("/api/doctor/checks") && res.request().method() === "GET",
  );
  await page.getByTestId("doctor-run-quick").click();
  const doctorQuickResponse = await doctorQuickWaiter;
  expect(doctorQuickResponse.status()).toBeLessThan(500);

  // Browser must stay gateway-only.
  expect(directUpstreamCalls).toEqual([]);
});
