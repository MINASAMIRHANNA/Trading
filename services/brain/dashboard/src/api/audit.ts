export type AuditItem = {
  id: number;
  ts_utc: string;
  actor: string;
  action: string;
  role?: string | null;
  target_id?: string | null;
  trace_id?: string | null;
  request_json?: any;
  response_json?: any;
  ok: boolean;
};

export type AuditResponse = {
  ok: boolean;
  items?: AuditItem[];
  error?: string;
};

export async function fetchAudit(limit: number = 200): Promise<AuditResponse> {
  const r = await fetch(`/api/audit?limit=${encodeURIComponent(String(limit))}`);
  const json = await r.json();
  return json;
}


export async function replayAudit(auditId: number): Promise<any> {
  const r = await fetch(`/api/audit/${encodeURIComponent(String(auditId))}/replay`, {
    method: "POST",
  });
  let json: any = null;
  try {
    json = await r.json();
  } catch {
    const t = await r.text();
    throw new Error(t || `HTTP ${r.status}`);
  }
  if (!r.ok) {
    throw new Error(json?.detail || json?.error || `HTTP ${r.status}`);
  }
  return json;
}
