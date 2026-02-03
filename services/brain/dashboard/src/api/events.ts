export type SharedEvent = {
  id: number;
  bot_role: string;
  event_type: string;
  data: any;
  created_at: string;
};

export type EventsResponse = {
  ok: boolean;
  items?: SharedEvent[];
  count?: number;
  error?: string;
};

export async function fetchEvents(params: {
  role?: string;
  event_type?: string;
  limit?: number;
  since_id?: number;
  order?: "asc" | "desc";
} = {}): Promise<EventsResponse> {
  const qs = new URLSearchParams();
  if (params.role) qs.set("role", params.role);
  if (params.event_type) qs.set("event_type", params.event_type);
  if (typeof params.limit === "number") qs.set("limit", String(params.limit));
  if (typeof params.since_id === "number") qs.set("since_id", String(params.since_id));
  if (params.order) qs.set("order", params.order);

  const r = await fetch(`/api/events?${qs.toString()}`);
  const json = await r.json();
  return json;
}

export function openEventsStream(params: {
  role?: string;
  event_type?: string;
  since_id?: number;
  interval_ms?: number;
} = {}): EventSource {
  const qs = new URLSearchParams();
  if (params.role) qs.set("role", params.role);
  if (params.event_type) qs.set("event_type", params.event_type);
  if (typeof params.since_id === "number") qs.set("since_id", String(params.since_id));
  if (typeof params.interval_ms === "number") qs.set("interval_ms", String(params.interval_ms));
  return new EventSource(`/api/events/stream?${qs.toString()}`);
}
