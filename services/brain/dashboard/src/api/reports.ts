import { api } from "./client";

export async function fetchPaperArena(params: { from?: string; to?: string } = {}) {
  const { data } = await api.get("/reports/paper-arena", { params });
  return data;
}

export async function fetchAnalytics(params: { from?: string; to?: string } = {}) {
  const { data } = await api.get("/reports/analytics", { params });
  return data;
}

export async function fetchDeepAudit(params: { trace_id?: string; role?: string; limit?: number } = {}) {
  const { data } = await api.get("/reports/deep_audit", { params });
  return data;
}

export async function fetchDailySummary(params: Record<string, any> = {}) {
  const { data } = await api.get("/reports/daily_summary", { params });
  return data;
}

export async function fetchStrategyCompare(params: Record<string, any> = {}) {
  const { data } = await api.get("/reports/strategy_compare", { params });
  return data;
}

export async function fetchAuditTrace(trace_id: string) {
  const { data } = await api.get("/reports/audit/trace", { params: { trace_id } });
  return data;
}

export async function fetchDataQuality(params: { role?: string; from?: string; to?: string } = {}) {
  const { data } = await api.get("/reports/data-quality", { params });
  return data;
}

export async function exportReport(params: { type: string; format?: string; role?: string; from?: string; to?: string }) {
  const { data } = await api.get("/reports/export", { params });
  return data;
}

export async function fetchPnlBreakdown(params: { role?: string; period?: string; from?: string; to?: string } = {}) {
  const { data } = await api.get("/reports/pnl-breakdown", { params });
  return data;
}

export async function fetchStrategyPerformance(params: { role?: string; from?: string; to?: string } = {}) {
  const { data } = await api.get("/reports/strategy-performance", { params });
  return data;
}

export async function fetchFeesSlippage(params: { role?: string; from?: string; to?: string } = {}) {
  const { data } = await api.get("/reports/fees-slippage", { params });
  return data;
}

export async function fetchRiskTimeline(params: { role?: string; limit?: number } = {}) {
  const { data } = await api.get("/reports/risk-timeline", { params });
  return data;
}
