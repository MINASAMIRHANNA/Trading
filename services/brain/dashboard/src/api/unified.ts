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

export async function queueUnifiedCloseAll(role: UnifiedRole, reason?: string): Promise<any> {
  const body: any = {};
  if (reason) body.reason = reason;
  const { data } = await api.post(`/unified/${role}/commands/close_all`, body);
  return data;
}

export async function queueUnifiedKillSwitch(role: UnifiedRole, enabled: boolean, reason?: string): Promise<any> {
  const body: any = { enabled };
  if (reason) body.reason = reason;
  const { data } = await api.post(`/unified/${role}/commands/kill_switch`, body);
  return data;
}

export async function fetchUnifiedTrades(role: UnifiedRole, limit: number = 50, status?: string, symbol?: string): Promise<any> {
  const params: any = { limit };
  if (status && status !== "all") params.status = status;
  if (symbol) params.symbol = symbol;
  const { data } = await api.get(`/unified/${role}/trades`, { params });
  return data;
}

export async function fetchUnifiedTrade(role: UnifiedRole, tradeId: number): Promise<any> {
  const { data } = await api.get(`/unified/${role}/trades/${tradeId}`);
  return data;
}

export async function fetchUnifiedEquityHistory(role: UnifiedRole, params: { limit?: number; from_ts?: string; to_ts?: string } = {}): Promise<any> {
  const { data } = await api.get(`/unified/${role}/equity_history`, { params });
  return data;
}

export async function fetchUnifiedPerfMetrics(role: UnifiedRole, params: { limit?: number; from_ts?: string; to_ts?: string } = {}): Promise<any> {
  const { data } = await api.get(`/unified/${role}/perf_metrics`, { params });
  return data;
}

export async function fetchUnifiedCommandsHistory(role: UnifiedRole, limit: number = 50): Promise<any> {
  const { data } = await api.get(`/unified/${role}/commands/history`, { params: { limit } });
  return data;
}

export async function fetchUnifiedSignal(role: UnifiedRole, signalId: number): Promise<any> {
  const { data } = await api.get(`/unified/${role}/signals/${signalId}`);
  return data;
}

export async function fetchUnifiedSyncStatus(role: UnifiedRole): Promise<any> {
  const { data } = await api.get(`/unified/sync/status`, { params: { role } });
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

export async function fetchUnifiedSettings(role: UnifiedRole): Promise<any> {
  const { data } = await api.get(`/unified/${role}/settings`);
  return data;
}

export async function updateUnifiedSettings(role: UnifiedRole, payload: Record<string, any>): Promise<any> {
  const { data } = await api.post(`/unified/${role}/settings`, payload);
  return data;
}

export async function fetchUnifiedEnvSecrets(role: UnifiedRole): Promise<any> {
  const { data } = await api.get(`/unified/${role}/env_secrets`);
  return data;
}

export async function updateUnifiedEnvSecrets(role: UnifiedRole, payload: Record<string, any>): Promise<any> {
  const { data } = await api.post(`/unified/${role}/env_secrets`, payload);
  return data;
}

export async function clearUnifiedKillSwitch(role: UnifiedRole): Promise<any> {
  const { data } = await api.post(`/unified/${role}/control/clear_kill_switch`, {});
  return data;
}

export async function restartUnifiedBot(role: UnifiedRole): Promise<any> {
  const { data } = await api.post(`/unified/${role}/control/restart_bot`, {});
  return data;
}

export async function restartUnifiedMonitor(role: UnifiedRole): Promise<any> {
  const { data } = await api.post(`/unified/${role}/control/restart_monitor`, {});
  return data;
}

export async function getAutopilot(): Promise<any> {
  const { data } = await api.get("/unified/autopilot");
  return data;
}

export async function setAutopilotGlobal(global_mode: "OFF" | "SHADOW" | "TESTNET" | "LIVE"): Promise<any> {
  const { data } = await api.post("/unified/autopilot", { global_mode });
  return data;
}

export async function setAutopilotRole(role: UnifiedRole, role_mode: "OFF" | "SHADOW" | "TESTNET" | "LIVE"): Promise<any> {
  const { data } = await api.post(`/unified/autopilot/${role}`, { role_mode });
  return data;
}
