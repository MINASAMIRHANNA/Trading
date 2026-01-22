import { api } from "./client";

export async function fetchFeatureImportance(symbol?: string) {
  const res = await api.get("/ml/importance", {
    params: { symbol },
  });
  return res.data;
}
