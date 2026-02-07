import { api } from "./client";
import type { UnifiedRole } from "./unified";

export async function fetchMinaStatus(role: UnifiedRole): Promise<any> {
  const { data } = await api.get(`/mina/${role}/status`);
  return data;
}

export async function fetchMinaAnalytics(role: UnifiedRole): Promise<any> {
  const { data } = await api.get(`/mina/${role}/analytics`);
  return data;
}

export async function fetchMinaAudit(
  role: UnifiedRole,
  params: { symbol: string; interval?: string; start?: string; end?: string },
): Promise<any> {
  const q: Record<string, string> = {
    symbol: params.symbol,
  };
  if (params.interval) q.interval = params.interval;
  if (params.start) q.start = params.start;
  if (params.end) q.end = params.end;
  const { data } = await api.get(`/mina/${role}/audit`, { params: q });
  return data;
}
