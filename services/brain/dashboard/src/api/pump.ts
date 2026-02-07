import { api } from "./client";

export type PumpCandidateStatus = "PENDING" | "WATCH" | "APPROVED" | "REJECTED" | "EXECUTED";

export async function getPumpStatus(): Promise<any> {
  const { data } = await api.get("/mina/pump/pump/status");
  return data;
}

export async function listPumpCandidates(params: { limit?: number; status?: string } = {}): Promise<any> {
  const { data } = await api.get("/mina/pump/pump/candidates", { params });
  return data;
}

export async function approvePumpCandidate(payload: { id: number; note?: string }): Promise<any> {
  const { data } = await api.post("/mina/pump/pump/candidates/approve", payload);
  return data;
}

export async function rejectPumpCandidate(payload: { id: number; note?: string }): Promise<any> {
  const { data } = await api.post("/mina/pump/pump/candidates/reject", payload);
  return data;
}

export async function promotePumpCandidate(payload: {
  id: number;
  side: string;
  target_role: "paper" | "live";
  note?: string;
  live_confirm?: boolean;
  live_confirm_ack?: boolean;
  live_pin?: string;
}): Promise<any> {
  const { data } = await api.post("/pump/candidates/promote", payload);
  return data;
}

export async function setPumpLabel(payload: { symbol: string; timestamp_ms: number; label: string; note?: string }): Promise<any> {
  const { data } = await api.post("/mina/pump/pump/label", payload);
  return data;
}

export async function getPumpStats(): Promise<any> {
  const { data } = await api.get("/mina/pump/stats");
  return data;
}

export async function listPumpTrades(params: { limit?: number; status?: string } = {}): Promise<any> {
  const { data } = await api.get("/mina/pump/trades", { params });
  return data;
}
