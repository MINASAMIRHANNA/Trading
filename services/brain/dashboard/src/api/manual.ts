import { api } from "./client";

export type ManualExecutePayload = {
  role: "paper" | "live";
  symbol: string;
  amount_usd: number;
  market: "futures" | "spot";
  direction: "LONG" | "SHORT" | "BUY" | "SELL";
  time_in_force?: string;
  leverage?: number;
  trace_id?: string;
  live_confirm?: boolean;
  live_confirm_ack?: boolean;
  live_pin?: string;
};

export async function executeManualTrade(payload: ManualExecutePayload) {
  const { data } = await api.post("/manual/execute", payload);
  return data;
}
