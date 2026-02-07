import { api } from "./client";

export async function fetchTelegramSettings() {
  const { data } = await api.get("/notifications/settings");
  return data;
}

export async function updateTelegramSettings(payload: Record<string, any>) {
  const { data } = await api.post("/notifications/settings", payload);
  return data;
}

export async function testTelegram() {
  const { data } = await api.post("/notifications/test");
  return data;
}

export async function fetchAlertRules() {
  const { data } = await api.get("/notifications/settings");
  const s = data?.settings || {};
  return {
    ok: true,
    items: [
      {
        id: 1,
        enabled: Boolean(s.enabled),
        filters: {
          notify_signals_created: Boolean(s.notify_signals_created),
          notify_signals_approved: Boolean(s.notify_signals_approved),
          notify_signals_opened: Boolean(s.notify_signals_opened),
          notify_signals_closed: Boolean(s.notify_signals_closed),
          notify_errors: Boolean(s.notify_errors),
          notify_service_down: Boolean(s.notify_service_down),
          notify_sync_lag: Boolean(s.notify_sync_lag),
          notify_error_spike: Boolean(s.notify_error_spike),
          notify_dd_breach: Boolean(s.notify_dd_breach),
          notify_kill_switch: Boolean(s.notify_kill_switch),
        },
        updated_at: null,
      },
    ],
  };
}

export async function updateAlertRules(payload: Record<string, any>) {
  const filters = payload?.filters || {};
  const mapped = {
    enabled: payload?.enabled,
    notify_signals_created: filters.notify_signals_created,
    notify_signals_approved: filters.notify_signals_approved,
    notify_signals_opened: filters.notify_signals_opened,
    notify_signals_closed: filters.notify_signals_closed,
    notify_errors: filters.notify_errors,
    notify_service_down: filters.notify_service_down,
    notify_sync_lag: filters.notify_sync_lag,
    notify_error_spike: filters.notify_error_spike,
    notify_dd_breach: filters.notify_dd_breach,
    notify_kill_switch: filters.notify_kill_switch,
  };
  const { data } = await api.post("/notifications/settings", mapped);
  return data;
}

export async function fetchAlertHistory(limit: number = 200) {
  const { data } = await api.get("/alerts/history", { params: { limit } });
  return data;
}
