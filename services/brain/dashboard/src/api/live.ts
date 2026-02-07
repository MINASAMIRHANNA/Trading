import { api } from "./client";

export type LiveSafetyPolicyPayload = {
  execution_enabled?: boolean;
  double_confirm_required?: boolean;
  pin_enabled?: boolean;
  live_pin?: string;
  clear_pin?: boolean;
  max_daily_loss?: number;
  max_open_positions?: number;
  max_leverage?: number;
  max_notional?: number;
  cooldown_sec?: number;
  rollout_stage?: "LIVE-0" | "LIVE-1" | "LIVE-2";
  live_confirm?: boolean;
  live_confirm_ack?: boolean;
  live_pin_confirm?: string;
};

export async function fetchLiveSafetyPolicy(includeRuntime: boolean = true) {
  const { data } = await api.get("/live/safety_policy", { params: { include_runtime: includeRuntime } });
  return data;
}

export async function updateLiveSafetyPolicy(payload: LiveSafetyPolicyPayload) {
  const { data } = await api.post("/live/safety_policy", payload);
  return data;
}

export async function fetchLiveRollout() {
  const { data } = await api.get("/live/rollout");
  return data;
}

export async function setLiveRollout(stage: "LIVE-0" | "LIVE-1" | "LIVE-2", payload: Record<string, any> = {}) {
  const { data } = await api.post("/live/rollout", { stage, ...payload });
  return data;
}
