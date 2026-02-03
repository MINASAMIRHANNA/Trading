import { api } from "./client";

export async function fetchOverview(symbol?: string) {
  const res = await api.get("/overview", {
    params: { symbol },
  });
  return res.data;
}
