import { api } from "./client";

export async function listWebhooks() {
  const { data } = await api.get("/webhooks");
  return data;
}

export async function createWebhook(payload: { url: string; event_types: string[]; enabled?: boolean }) {
  const { data } = await api.post("/webhooks", payload);
  return data;
}

export async function updateWebhook(id: number, payload: Record<string, any>) {
  const { data } = await api.patch(`/webhooks/${id}`, payload);
  return data;
}

export async function deleteWebhook(id: number) {
  const { data } = await api.delete(`/webhooks/${id}`);
  return data;
}

export async function testWebhook(id: number) {
  const { data } = await api.post(`/webhooks/test/${id}`);
  return data;
}
