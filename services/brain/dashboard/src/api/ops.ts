import { api } from "./client";

export async function fetchOpsStatus(role: string = "live") {
  const { data } = await api.get("/ops/status", { params: { role } });
  return data;
}

export async function fetchOpsPositions(role: string = "live", limit: number = 50) {
  const { data } = await api.get("/ops/positions", { params: { role, limit } });
  return data;
}

export async function fetchOpsErrors(role: string = "all", limit: number = 100) {
  const { data } = await api.get("/ops/errors", { params: { role, limit } });
  return data;
}

export async function sendOpsCommand(payload: Record<string, any>) {
  const { data } = await api.post("/ops/command", payload);
  return data;
}

export async function queueMinaCommand(
  role: string,
  cmd: string,
  params: Record<string, any> = {},
  guard: { live_confirm?: boolean; live_confirm_ack?: boolean; live_pin?: string } = {},
) {
  const body = { cmd, params, ...guard };
  const { data } = await api.post(`/mina/${role}/commands/queue`, body);
  return data;
}
