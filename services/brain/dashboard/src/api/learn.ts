import { api } from "./client";

export async function fetchLearnState() {
  const { data } = await api.get("/learn/state");
  return data;
}

export async function fetchLearnStatus() {
  const { data } = await api.get("/learn/status");
  return data;
}

export async function fetchLearnKpis(params: { role?: "paper" | "live" | "pump" | "all"; window_days?: number } = {}) {
  const { data } = await api.get("/learn/kpis", { params });
  return data;
}

export async function triggerLearnSync() {
  const { data } = await api.post("/learn/sync");
  return data;
}

export async function triggerLearnTrain() {
  const { data } = await api.post("/learn/train");
  return data;
}

export async function triggerLearnTrainForRole(
  role: "paper" | "live" | "pump",
  payload: Record<string, any> = {},
) {
  const { data } = await api.post("/learn/train", { role, ...payload });
  return data;
}

export async function promoteLearnCandidate(role: "paper" | "live" | "pump", version?: string, payload: Record<string, any> = {}) {
  const body: Record<string, any> = { role };
  if (version) body.version = version;
  Object.assign(body, payload);
  const { data } = await api.post("/learn/promote", body);
  return data;
}

export async function rollbackLearnDeployed(role: "paper" | "live" | "pump", payload: Record<string, any> = {}) {
  const { data } = await api.post("/learn/rollback", { role, ...payload });
  return data;
}

export async function triggerLearnBacktest() {
  const { data } = await api.post("/learn/backtest");
  return data;
}

export async function fetchLearnConfig() {
  const { data } = await api.get("/learn/config");
  return data;
}

export async function updateLearnConfig(patch: Record<string, any>) {
  const { data } = await api.patch("/learn/config", patch);
  return data;
}
