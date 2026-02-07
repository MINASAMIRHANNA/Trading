import { useEffect, useMemo, useState } from "react";
import {
  connectBinance,
  disconnectBinance,
  downloadBinancePortfolioCsv,
  downloadPortfolioCsv,
  fetchBinancePortfolioAccount,
  fetchBinanceStatus,
  fetchPortfolioEquity,
  fetchPortfolioFees,
  fetchPortfolioSummary,
  fetchPortfolioTrades,
  fetchProjectMode as apiFetchProjectMode,
  setProjectMode as apiSetProjectMode,
  testBinance,
} from "../api/portfolio";
import { DataTable, KpiCard, Panel, SectionHeader, StatusBadge, formatNum, toneFromValue } from "../components/mina";
import { requestLiveGuard } from "../utils/liveGuard";

const ROLES = ["all", "paper", "live", "pump"] as const;

function normalizeUtcInput(value: string): string | undefined {
  const v = String(value || "").trim();
  if (!v) return undefined;
  if (/[zZ]$|[+-]\d{2}:\d{2}$/.test(v)) return v;
  if (/^\d{4}-\d{2}-\d{2}$/.test(v)) return `${v}T00:00:00Z`;
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(v)) return `${v}:00Z`;
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$/.test(v)) return `${v}Z`;
  return v;
}

function downloadBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(href);
}

function stampFilePart(): string {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

export default function Portfolio() {
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [summary, setSummary] = useState<any>(null);
  const [byRole, setByRole] = useState<Record<string, any>>({});
  const [fees, setFees] = useState<any[]>([]);
  const [trades, setTrades] = useState<any[]>([]);
  const [equity, setEquity] = useState<any[]>([]);
  const [role, setRole] = useState<(typeof ROLES)[number]>("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [testnet, setTestnet] = useState(true);
  const [binanceStatus, setBinanceStatus] = useState<{ connected: boolean; detail: string } | null>(null);
  const [binanceAccount, setBinanceAccount] = useState<any>(null);
  const [connection, setConnection] = useState<any>(null);
  const [projectMode, setProjectMode] = useState<"TESTNET" | "LIVE">("TESTNET");
  const [projectRoles, setProjectRoles] = useState<Record<string, any>>({});
  const [modeBusy, setModeBusy] = useState(false);

  const buildBinanceErrorDetail = (res: any) => {
    if (res?.error === "testnet_mismatch" && typeof res?.suggested_testnet === "boolean") {
      return res.suggested_testnet
        ? "Credentials seem to be Testnet. Switch network to Testnet and connect again."
        : "Credentials seem to be Mainnet. Switch network to Mainnet and connect again.";
    }
    const spot = res?.spot?.error_msg ? `Spot: ${res.spot.error_msg}` : "";
    const futures = res?.futures?.error_msg ? `Futures: ${res.futures.error_msg}` : "";
    return [spot, futures].filter(Boolean).join(" | ") || res?.error || "Validation failed.";
  };

  const load = async () => {
    try {
      const fromUtc = normalizeUtcInput(from);
      const toUtc = normalizeUtcInput(to);
      const [s, t, f, eq, b] = await Promise.all([
        fetchPortfolioSummary({ role, from: fromUtc, to: toUtc }),
        fetchPortfolioTrades({ role, from: fromUtc, to: toUtc, limit: 200 }),
        fetchPortfolioFees({ role, from: fromUtc, to: toUtc }),
        fetchPortfolioEquity({ role, from: fromUtc, to: toUtc, limit: 600 }),
        fetchBinancePortfolioAccount({ from: fromUtc, to: toUtc }).catch(() => null),
      ]);
      setSummary(s?.summary || s || {});
      setByRole(s?.by_role || {});
      setTrades(t?.items || []);
      setFees(Array.isArray(f?.items) ? f.items : []);
      setEquity(eq?.items || []);
      setConnection(s?.connection || null);
      setBinanceAccount(b);
      setMessage("");
    } catch (err: any) {
      setMessage(err?.message || "Failed to load portfolio.");
    }
  };

  const loadBinanceStatus = async () => {
    try {
      const s = await fetchBinanceStatus(true);
      setTestnet(Boolean(s?.testnet ?? true));
      if (s?.connected) {
        setBinanceStatus({ connected: true, detail: s?.testnet ? "Connected (Testnet)." : "Connected (Mainnet)." });
      } else if (s?.has_credentials) {
        setBinanceStatus({ connected: false, detail: buildBinanceErrorDetail(s) });
      } else {
        setBinanceStatus({ connected: false, detail: "Not connected yet. Add key + secret to connect." });
      }
    } catch {
      setBinanceStatus({ connected: false, detail: "Unable to fetch Binance status from Gateway." });
    }
  };

  const loadProjectMode = async () => {
    try {
      const data = await apiFetchProjectMode();
      setProjectMode((String(data?.project_mode || "TESTNET").toUpperCase() === "LIVE" ? "LIVE" : "TESTNET") as "LIVE" | "TESTNET");
      setProjectRoles(data?.roles || {});
    } catch {
      setProjectRoles({});
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role, from, to]);

  useEffect(() => {
    void loadBinanceStatus();
    void loadProjectMode();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const exposureRows = useMemo(() => {
    return Object.entries(summary?.symbols || {}).map(([symbol, pnl]) => ({ symbol, pnl }));
  }, [summary]);

  const paperLiveRows = useMemo(
    () => ["paper", "live"].map((r) => ({ role: r, ...(byRole?.[r] || {}) })),
    [byRole],
  );

  const kpis = [
    { label: "Realized PnL", value: summary?.realized_pnl, tone: toneFromValue(summary?.realized_pnl) },
    { label: "Floating PnL", value: summary?.floating_pnl ?? summary?.unrealized_pnl, tone: toneFromValue(summary?.floating_pnl ?? summary?.unrealized_pnl) },
    { label: "Win Rate", value: summary?.win_rate, suffix: "%" },
    { label: "Total Fees", value: summary?.total_fees, tone: "warn" as const },
    { label: "Trades", value: summary?.total_trades },
    { label: "Wins / Losses", value: `${summary?.wins ?? 0} / ${summary?.losses ?? 0}` },
  ];

  const binanceSummary = binanceAccount?.summary || {};
  const binanceKpis = [
    { label: "Balance (USDT)", value: binanceSummary?.balance_usdt, tone: "neutral" as const },
    { label: "Equity (USDT)", value: binanceSummary?.equity_usdt, tone: toneFromValue(binanceSummary?.equity_usdt) },
    { label: "Realized PnL", value: binanceSummary?.realized_pnl, tone: toneFromValue(binanceSummary?.realized_pnl) },
    { label: "Unrealized PnL", value: binanceSummary?.unrealized_pnl, tone: toneFromValue(binanceSummary?.unrealized_pnl) },
    { label: "Total Fees", value: binanceSummary?.total_fees, tone: "warn" as const },
    { label: "Network", value: binanceAccount?.testnet ? "TESTNET" : "MAINNET", tone: binanceAccount?.testnet ? ("good" as const) : ("warn" as const) },
  ];

  const runConnect = async () => {
    if (!apiKey || !apiSecret) {
      setMessage("API key and secret are required.");
      return;
    }
    setBusy(true);
    try {
      await connectBinance(apiKey, apiSecret, testnet);
      setApiSecret("");
      const verify = await testBinance();
      if (verify?.ok) {
        setBinanceStatus({ connected: true, detail: testnet ? "Connected (Testnet)." : "Connected (Mainnet)." });
        setMessage("Binance connected successfully.");
      } else {
        const detail = buildBinanceErrorDetail(verify);
        setBinanceStatus({ connected: false, detail });
        setMessage("Credentials saved, but validation failed.");
      }
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Binance connect failed.");
      setBinanceStatus({ connected: false, detail: err?.message || "Connect failed." });
    } finally {
      setBusy(false);
    }
  };

  const runTest = async () => {
    setBusy(true);
    try {
      const res = await testBinance();
      if (res?.ok) {
        setBinanceStatus({ connected: true, detail: res?.testnet ? "Connected (Testnet)." : "Connected (Mainnet)." });
        setMessage("Binance connectivity test passed.");
      } else {
        const detail = buildBinanceErrorDetail(res);
        setBinanceStatus({ connected: false, detail });
        setMessage("Binance test failed.");
      }
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Binance test failed.");
      setBinanceStatus({ connected: false, detail: err?.message || "Validation failed." });
    } finally {
      setBusy(false);
    }
  };

  const runDisconnect = async () => {
    setBusy(true);
    try {
      await disconnectBinance();
      setMessage("Binance credentials removed.");
      setBinanceStatus({ connected: false, detail: "Disconnected." });
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Disconnect failed.");
    } finally {
      setBusy(false);
    }
  };

  const exportDbCsv = async () => {
    setBusy(true);
    try {
      const blob = await downloadPortfolioCsv({
        role,
        from: normalizeUtcInput(from),
        to: normalizeUtcInput(to),
        limit: 10000,
      });
      downloadBlob(blob, `portfolio_${role}_${stampFilePart()}.csv`);
      setMessage("Portfolio CSV exported.");
    } catch (err: any) {
      setMessage(err?.message || "Failed to export portfolio CSV.");
    } finally {
      setBusy(false);
    }
  };

  const exportBinanceCsv = async () => {
    setBusy(true);
    try {
      const blob = await downloadBinancePortfolioCsv({
        from: normalizeUtcInput(from),
        to: normalizeUtcInput(to),
      });
      downloadBlob(blob, `binance_portfolio_${stampFilePart()}.csv`);
      setMessage("Binance CSV exported.");
    } catch (err: any) {
      setMessage(err?.message || "Failed to export Binance CSV.");
    } finally {
      setBusy(false);
    }
  };

  const switchProjectMode = async (target: "TESTNET" | "LIVE") => {
    let guard: Record<string, any> = {};
    if (target === "LIVE") {
      const payload = await requestLiveGuard("Switch project mode to LIVE", true);
      if (!payload) return;
      guard = payload;
    }
    setModeBusy(true);
    try {
      const out = await apiSetProjectMode(target, guard);
      setProjectMode((String(out?.project_mode || target).toUpperCase() === "LIVE" ? "LIVE" : "TESTNET") as "LIVE" | "TESTNET");
      setProjectRoles(out?.roles || {});
      setMessage(`Project mode switched to ${target}.`);
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Failed to switch project mode.");
    } finally {
      setModeBusy(false);
    }
  };

  return (
    <div>
      <SectionHeader
        title="Portfolio"
        subtitle="Unified paper/live portfolio analytics with optional Binance read-only integration through Gateway."
        right={message ? <span className="muted">{message}</span> : null}
      />

      {projectMode === "LIVE" ? (
        <Panel title="Live Role Warning">
          <div className="filters-row">
            <StatusBadge text="PROJECT LIVE MODE" tone="warn" />
            <span className="muted">
              Live mode changes require double-confirm and optional PIN policy from Live Safety controls.
            </span>
          </div>
        </Panel>
      ) : null}

      <Panel title="Filters" subtitle="UTC date range + role scope (applied server-side).">
        <div className="filters-row">
          <select data-testid="portfolio-role" className="dark-select" value={role} onChange={(e) => setRole(e.target.value as any)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
          <input data-testid="portfolio-from" className="dark-input" placeholder="From UTC (ISO)" value={from} onChange={(e) => setFrom(e.target.value)} />
          <input data-testid="portfolio-to" className="dark-input" placeholder="To UTC (ISO)" value={to} onChange={(e) => setTo(e.target.value)} />
          <button data-testid="portfolio-apply" className="action-btn primary" onClick={() => void load()}>
            Apply
          </button>
          <button data-testid="portfolio-export-db" className="action-btn" disabled={busy} onClick={() => void exportDbCsv()}>
            Export DB CSV
          </button>
          <button data-testid="portfolio-export-binance" className="action-btn" disabled={busy} onClick={() => void exportBinanceCsv()}>
            Export Binance CSV
          </button>
        </div>
      </Panel>

      <Panel title="Project Trading Mode" subtitle="Switch runtime mode for the whole project via Gateway.">
        <div className="filters-row">
          <StatusBadge text={`PROJECT: ${projectMode}`} tone={projectMode === "LIVE" ? "warn" : "good"} />
          <button data-testid="portfolio-switch-testnet" className="action-btn" disabled={modeBusy || projectMode === "TESTNET"} onClick={() => void switchProjectMode("TESTNET")}>
            Switch to TESTNET
          </button>
          <button data-testid="portfolio-switch-live" className="action-btn bad" disabled={modeBusy || projectMode === "LIVE"} onClick={() => void switchProjectMode("LIVE")}>
            Switch to LIVE
          </button>
          <span className="muted">`paper` stays PAPER mode by design.</span>
        </div>
        <div style={{ marginTop: 10 }}>
          <DataTable
            rows={Object.entries(projectRoles || {}).map(([r, v]) => ({ role: r, ...(v as any) }))}
            emptyText="Project mode details unavailable."
            columns={[
              { key: "role", title: "Role", render: (row: any) => row.role },
              { key: "mode", title: "Mode", render: (row: any) => row.mode || "—" },
              {
                key: "use_testnet",
                title: "Use Testnet",
                render: (row: any) => <StatusBadge text={row.use_testnet ? "TRUE" : "FALSE"} tone={row.use_testnet ? "good" : "warn"} />,
              },
              {
                key: "effective_mode",
                title: "Effective",
                render: (row: any) => (
                  <StatusBadge text={row.effective_mode || "—"} tone={String(row.effective_mode || "").toUpperCase() === "LIVE" ? "warn" : "good"} />
                ),
              },
              {
                key: "kill_switch",
                title: "Kill Switch",
                render: (row: any) => (
                  <StatusBadge text={String(row.kill_switch || "0") === "1" ? "ON" : "OFF"} tone={String(row.kill_switch || "0") === "1" ? "bad" : "good"} />
                ),
              },
            ]}
          />
        </div>
      </Panel>

      <Panel title="Exchange Connection (Read-only Status)">
        <div className="filters-row">
          <StatusBadge text={connection?.enabled ? "Enabled" : "Not connected / disabled"} tone={connection?.enabled ? "good" : "warn"} />
          <span className="muted">
            {connection?.enabled
              ? "Exchange integration settings exist in Gateway."
              : "Live exchange integration is not enabled. Portfolio uses DB-only metrics."}
          </span>
        </div>
      </Panel>

      <Panel title="Binance Integration" subtitle="Credentials are stored in Gateway settings only.">
        <div className="filters-row">
          <input data-testid="portfolio-binance-key" className="dark-input" placeholder="API Key" value={apiKey} onChange={(e) => setApiKey(e.target.value)} autoComplete="off" />
          <input
            data-testid="portfolio-binance-secret"
            className="dark-input"
            placeholder="API Secret"
            type="password"
            value={apiSecret}
            onChange={(e) => setApiSecret(e.target.value)}
            autoComplete="new-password"
          />
          <select data-testid="portfolio-binance-network" className="dark-select" value={testnet ? "testnet" : "mainnet"} onChange={(e) => setTestnet(e.target.value === "testnet")}>
            <option value="testnet">Testnet</option>
            <option value="mainnet">Mainnet</option>
          </select>
          <button data-testid="portfolio-binance-connect" className="action-btn primary" disabled={busy} onClick={() => void runConnect()}>
            Connect
          </button>
          <button data-testid="portfolio-binance-validate" className="action-btn" disabled={busy} onClick={() => void runTest()}>
            Validate
          </button>
          <button data-testid="portfolio-binance-disconnect" className="action-btn bad" disabled={busy} onClick={() => void runDisconnect()}>
            Disconnect
          </button>
          <button data-testid="portfolio-binance-refresh" className="action-btn" disabled={busy} onClick={() => void loadBinanceStatus()}>
            Refresh Status
          </button>
        </div>
        <div className="filters-row" style={{ marginTop: 10 }}>
          <StatusBadge text={binanceStatus?.connected ? "CONNECTED" : "NOT CONNECTED"} tone={binanceStatus?.connected ? "good" : "bad"} />
          <span className="muted">{binanceStatus?.detail || "Use API Key + Secret, then Validate."}</span>
        </div>
      </Panel>

      <Panel title="KPIs (DB Aggregation)">
        <div className="kpi-grid">
          {kpis.map((k) => (
            <KpiCard
              key={k.label}
              label={k.label}
              value={typeof k.value === "number" ? `${formatNum(k.value)}${k.suffix || ""}` : k.value ?? "—"}
              tone={(k.tone as any) || "neutral"}
            />
          ))}
        </div>
      </Panel>

      <Panel title="Paper vs Live Split" subtitle="Clear separation of paper and live metrics.">
        <DataTable
          rows={paperLiveRows}
          emptyText="No paper/live metrics available."
          columns={[
            { key: "role", title: "Role", render: (row: any) => <StatusBadge text={String(row.role).toUpperCase()} tone={row.role === "live" ? "warn" : "good"} /> },
            { key: "total_trades", title: "Trades", render: (row: any) => row.total_trades ?? 0 },
            { key: "wins", title: "Wins", render: (row: any) => row.wins ?? 0 },
            { key: "losses", title: "Losses", render: (row: any) => row.losses ?? 0 },
            { key: "win_rate", title: "Win Rate", render: (row: any) => `${formatNum(row.win_rate ?? 0)}%` },
            {
              key: "realized_pnl",
              title: "Realized PnL",
              render: (row: any) => <StatusBadge text={formatNum(row.realized_pnl ?? 0)} tone={toneFromValue(row.realized_pnl ?? 0)} />,
            },
            {
              key: "floating_pnl",
              title: "Floating PnL",
              render: (row: any) => <StatusBadge text={formatNum(row.floating_pnl ?? 0)} tone={toneFromValue(row.floating_pnl ?? 0)} />,
            },
            { key: "total_fees", title: "Fees", render: (row: any) => formatNum(row.total_fees ?? 0) },
          ]}
        />
      </Panel>

      <Panel title="Binance Account (Read-only)">
        {!binanceAccount?.connected ? (
          <div className="filters-row">
            <StatusBadge text="Not connected / disabled" tone="warn" />
            <span className="muted">{binanceAccount?.message || "No Binance portfolio connection. DB metrics remain available."}</span>
          </div>
        ) : (
          <>
            <div className="kpi-grid">
              {binanceKpis.map((k) => (
                <KpiCard
                  key={k.label}
                  label={k.label}
                  value={typeof k.value === "number" ? formatNum(k.value, 4) : k.value ?? "—"}
                  tone={(k.tone as any) || "neutral"}
                />
              ))}
            </div>
            <div className="grid-2" style={{ marginTop: 10 }}>
              <Panel title="Spot Balances">
                <DataTable
                  rows={binanceAccount?.balances || []}
                  emptyText="No non-zero balances."
                  columns={[
                    { key: "asset", title: "Asset", render: (row: any) => row.asset || "—" },
                    { key: "free", title: "Free", render: (row: any) => formatNum(row.free, 8) },
                    { key: "locked", title: "Locked", render: (row: any) => formatNum(row.locked, 8) },
                    { key: "total", title: "Total", render: (row: any) => formatNum(row.total, 8) },
                  ]}
                />
              </Panel>
              <Panel title="Futures Positions">
                <DataTable
                  rows={binanceAccount?.positions || []}
                  emptyText="No open futures positions."
                  columns={[
                    { key: "symbol", title: "Symbol", render: (row: any) => row.symbol || "—" },
                    { key: "position_amt", title: "Qty", render: (row: any) => formatNum(row.position_amt, 5) },
                    { key: "entry_price", title: "Entry", render: (row: any) => formatNum(row.entry_price, 4) },
                    { key: "mark_price", title: "Mark", render: (row: any) => formatNum(row.mark_price, 4) },
                    { key: "leverage", title: "Lev", render: (row: any) => formatNum(row.leverage, 2) },
                    {
                      key: "unrealized_pnl",
                      title: "Unrealized PnL",
                      render: (row: any) => <StatusBadge text={formatNum(row.unrealized_pnl, 4)} tone={toneFromValue(row.unrealized_pnl)} />,
                    },
                  ]}
                />
              </Panel>
            </div>
          </>
        )}
      </Panel>

      <Panel title="Project Scope (All Roles)" subtitle="Unified Postgres reading for paper/live/pump through Gateway.">
        <DataTable
          rows={Object.entries(byRole || {}).map(([r, v]) => ({ role: r, ...(v as any) }))}
          emptyText="No role-level data yet."
          columns={[
            { key: "role", title: "Role", render: (row: any) => row.role },
            { key: "total_trades", title: "Trades", render: (row: any) => row.total_trades ?? 0 },
            { key: "wins", title: "Wins", render: (row: any) => row.wins ?? 0 },
            { key: "losses", title: "Losses", render: (row: any) => row.losses ?? 0 },
            { key: "win_rate", title: "Win Rate", render: (row: any) => `${formatNum(row.win_rate ?? 0)}%` },
            {
              key: "realized_pnl",
              title: "Realized PnL",
              render: (row: any) => <StatusBadge text={formatNum(row.realized_pnl ?? 0)} tone={toneFromValue(row.realized_pnl ?? 0)} />,
            },
          ]}
        />
      </Panel>

      <div className="grid-2">
        <Panel title="Equity Curve">
          <DataTable
            rows={equity}
            emptyText="No equity points in selected UTC range."
            pageSize={10}
            columns={[
              { key: "timestamp", title: "Time", render: (row: any) => row.timestamp || row.timestamp_ms || "—" },
              {
                key: "equity",
                title: "Equity",
                render: (row: any) => <StatusBadge text={formatNum(row.equity)} tone={toneFromValue(row.equity)} />,
              },
            ]}
          />
        </Panel>

        <Panel title="Exposure by Symbol">
          <DataTable
            rows={exposureRows}
            emptyText="No symbol exposure yet."
            columns={[
              { key: "symbol", title: "Symbol", render: (row: any) => row.symbol },
              {
                key: "pnl",
                title: "PnL",
                render: (row: any) => <StatusBadge text={formatNum(row.pnl)} tone={toneFromValue(row.pnl)} />,
              },
            ]}
          />
        </Panel>

        <Panel title="Fees Summary">
          <DataTable
            rows={fees}
            emptyText="No fees data."
            columns={[
              { key: "role", title: "Role", render: (row: any) => row.role || "—" },
              { key: "total_fees", title: "Total Fees", render: (row: any) => formatNum(row.total_fees ?? 0, 6) },
            ]}
          />
        </Panel>
      </div>

      <Panel title="Trades" subtitle="Latest trades in selected scope.">
        <DataTable
          rows={trades}
          emptyText="No trades available."
          columns={[
            { key: "role", title: "Role", render: (row: any) => row.role || role },
            { key: "id", title: "ID", render: (row: any) => row.id ?? "—" },
            { key: "symbol", title: "Symbol", render: (row: any) => row.symbol || row.pair || "—" },
            { key: "side", title: "Side", render: (row: any) => row.side || row.signal || "—" },
            { key: "status", title: "Status", render: (row: any) => row.status || "—" },
            {
              key: "pnl",
              title: "PnL",
              render: (row: any) => <StatusBadge text={formatNum(row.pnl || row.realized_pnl)} tone={toneFromValue(row.pnl || row.realized_pnl)} />,
            },
            { key: "opened", title: "Opened", render: (row: any) => row.opened_at || row.created_at || "—" },
            { key: "closed", title: "Closed", render: (row: any) => row.closed_at || row.closed_at_ms || "—" },
          ]}
        />
      </Panel>
    </div>
  );
}
