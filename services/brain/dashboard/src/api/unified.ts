import { api } from "./client";

export type UnifiedRole = "paper" | "live" | "pump";

export type UnifiedOverview = {
  brain: any;
  dashboards: Record<
    UnifiedRole,
    {
      stats: any;
      signals_preview: any;
    }
  >;
  ts_utc: string;
};

export async function fetchUnifiedOverview(): Promise<UnifiedOverview> {
  const { data } = await api.get("/unified/overview");
  return data;
}

export async function fetchUnifiedRoleSnapshot(role: UnifiedRole): Promise<any> {
  const { data } = await api.get(`/unified/${role}/snapshot`);
  return data;
}
export async function approveUnifiedSignal(role: UnifiedRole, signalId: number, note?: string, payload?: any): Promise<any> {
  const body: any = {};
  if (note) body.note = note;
  if (payload && typeof payload === "object") body.payload = payload;
  const { data } = await api.post(`/unified/${role}/signals/${signalId}/approve`, body);
  return data;
}

export async function rejectUnifiedSignal(role: UnifiedRole, signalId: number, reason?: string, note?: string): Promise<any> {
  const body: any = {};
  if (reason) body.reason = reason;
  if (note) body.note = note;
  const { data } = await api.post(`/unified/${role}/signals/${signalId}/reject`, body);
  return data;
}

export async function queueUnifiedCommand(role: UnifiedRole, cmd: string, params?: any): Promise<any> {
  const { data } = await api.post(`/unified/${role}/commands`, { cmd, params });
  return data;
}


export async function fetchUnifiedSignals(role: UnifiedRole, limit: number = 30, status?: string): Promise<any[]> {
  const params: any = { limit };
  if (status && status !== "all") params.status = status;
  const { data } = await api.get(`/unified/${role}/signals`, { params });
  return data;
}

export async function fetchUnifiedPositions(role: UnifiedRole): Promise<any> {
  const { data } = await api.get(`/unified/${role}/positions`);
  return data;
}

export async function fetchUnifiedStats(role: UnifiedRole): Promise<any> {
  const { data } = await api.get(`/unified/${role}/stats`);
  return data;
}

export async function fetchUnifiedSystemHealth(role: UnifiedRole): Promise<any> {
  const { data } = await api.get(`/unified/${role}/system_health`);
  return data;
}

export async function fetchUnifiedLogs(role: UnifiedRole, limit: number = 200): Promise<any> {
  const { data } = await api.get(`/unified/${role}/logs`, { params: { limit } });
  return data;
}



export async function fetchUnifiedSignalDecision(role: UnifiedRole, signalId: number): Promise<any> {
  const { data } = await api.get(`/unified/${role}/signals/${signalId}/decision`);
  return data;
}
