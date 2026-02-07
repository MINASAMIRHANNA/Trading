import { api } from "./client";

export async function fetchBrainInspectorOverview(role: string = "all") {
  const { data } = await api.get("/brain/inspector/overview", { params: { role } });
  return data;
}

export async function fetchBrainInspectorFeaturesSample(limit: number = 50) {
  try {
    const { data } = await api.get("/brain/inspector/features", { params: { limit } });
    return data;
  } catch {
    const { data } = await api.get("/brain/inspector/features_sample", { params: { limit } });
    return data;
  }
}

export async function fetchBrainInspectorDecisionTraces(params: {
  role?: string;
  trace_id?: string;
  decision_id?: number;
  limit?: number;
} = {}) {
  try {
    const { data } = await api.get("/brain/inspector/traces", { params });
    return data;
  } catch {
    const { data } = await api.get("/brain/inspector/decision_traces", { params });
    return data;
  }
}

export async function fetchHistoricalSnapshot(params: {
  role?: string;
  from?: string;
  to?: string;
  limit?: number;
} = {}) {
  const mapped = {
    role: params.role,
    from: params.from,
    to: params.to,
    limit: params.limit,
  };
  const { data } = await api.get("/snapshot", { params: mapped });
  return data;
}

export async function runHistoricalSnapshotAtUtc(payload: {
  role: string;
  symbol: string;
  market: "futures" | "spot";
  interval: "1m" | "5m" | "15m" | "1h" | "4h" | "1d";
  at_local: string;
  at_utc: string;
  trace_id?: string;
}) {
  const { data } = await api.post("/snapshot", payload);
  return data;
}
