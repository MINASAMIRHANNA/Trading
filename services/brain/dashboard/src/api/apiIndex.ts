import { api } from "./client";

export async function fetchApiIndex() {
  const { data } = await api.get("/api-docs/registry");
  return data;
}

export async function fetchGatewayOpenApi() {
  const { data } = await api.get("/openapi.json");
  return data;
}

export async function fetchBrainOpenApi() {
  const { data } = await api.get("/brain/openapi.json");
  return data;
}
