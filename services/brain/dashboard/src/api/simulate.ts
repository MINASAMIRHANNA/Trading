import { api } from "./client";

export interface SimulationRequest {
  symbol?: string;
  allowed_regimes?: number[];
  allowed_alignment?: number[];
}

export async function runSimulation(payload: SimulationRequest) {
  const res = await api.post("/simulate", payload);
  return res.data;
}
