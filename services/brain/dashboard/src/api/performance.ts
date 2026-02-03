import { api } from "./client";

export async function fetchRegimePerformance(symbol?: string) {
  const res = await api.get("/performance/by-regime", {
    params: { symbol },
  });
  return res.data;
}
