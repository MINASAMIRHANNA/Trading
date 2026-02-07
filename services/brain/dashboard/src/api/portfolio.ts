import { api } from "./client";

export async function connectBinance(api_key: string, api_secret: string, testnet: boolean = false) {
  const { data } = await api.post("/integrations/binance/connect", { api_key, api_secret, testnet });
  return data;
}

export async function testBinance() {
  const { data } = await api.post("/integrations/binance/test");
  return data;
}

export async function fetchBinanceStatus(check: boolean = true) {
  const { data } = await api.get("/integrations/binance/status", { params: { check } });
  return data;
}

export async function fetchProjectMode() {
  const { data } = await api.get("/project/mode");
  return data;
}

export async function setProjectMode(
  mode: "TESTNET" | "LIVE",
  payload: { live_confirm?: boolean; live_confirm_ack?: boolean; live_pin?: string } = {},
) {
  const { data } = await api.post("/project/mode", { mode, ...payload });
  return data;
}

export async function disconnectBinance() {
  const { data } = await api.post("/integrations/binance/disconnect");
  return data;
}

export async function fetchPortfolioSummary(params: { role?: string; from?: string; to?: string } = {}) {
  const mapped = {
    role: params.role,
    from: params.from,
    to: params.to,
  };
  const { data } = await api.get("/portfolio/summary", { params: mapped });
  return data;
}

export async function fetchPortfolioEquity(params: { role?: string; from?: string; to?: string; limit?: number } = {}) {
  const mapped = {
    role: params.role,
    from: params.from,
    to: params.to,
    limit: params.limit,
  };
  const { data } = await api.get("/portfolio/equity", { params: mapped });
  return data;
}

export async function fetchPortfolioTrades(params: { role?: string; from?: string; to?: string; symbol?: string; status?: string; limit?: number } = {}) {
  const mapped = {
    role: params.role,
    from: params.from,
    to: params.to,
    symbol: params.symbol,
    status: params.status,
    limit: params.limit,
  };
  const { data } = await api.get("/portfolio/trades", { params: mapped });
  return data;
}

export async function fetchPortfolioFees(params: { role?: string; from?: string; to?: string } = {}) {
  const mapped = {
    role: params.role,
    from: params.from,
    to: params.to,
  };
  const { data } = await api.get("/portfolio/fees", { params: mapped });
  return data;
}

export async function fetchBinancePortfolioAccount(params: { from?: string; to?: string } = {}) {
  const mapped = {
    from: params.from,
    to: params.to,
  };
  const { data } = await api.get("/portfolio/binance/account", { params: mapped });
  return data;
}

export async function downloadPortfolioCsv(params: { role?: string; from?: string; to?: string; limit?: number } = {}) {
  const { data } = await api.get("/portfolio/export.csv", {
    params: {
      role: params.role,
      from: params.from,
      to: params.to,
      limit: params.limit,
    },
    responseType: "blob",
  });
  return data as Blob;
}

export async function downloadBinancePortfolioCsv(params: { from?: string; to?: string } = {}) {
  const { data } = await api.get("/portfolio/binance/export.csv", {
    params: {
      from: params.from,
      to: params.to,
    },
    responseType: "blob",
  });
  return data as Blob;
}
