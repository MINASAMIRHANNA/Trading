import { useEffect, useState } from "react";
import { fetchTelegramSettings, testTelegram, updateTelegramSettings } from "../api/alerts";
import { Panel, SectionHeader, StatusPill } from "../components/mina";

export default function Alerts() {
  const [enabled, setEnabled] = useState(true);
  const [chatId, setChatId] = useState("");
  const [botToken, setBotToken] = useState("");
  const [patcherSettingsKey, setPatcherSettingsKey] = useState("");
  const [hasToken, setHasToken] = useState(false);

  const [notifySignalsCreated, setNotifySignalsCreated] = useState(true);
  const [notifySignalsApproved, setNotifySignalsApproved] = useState(true);
  const [notifySignalsOpened, setNotifySignalsOpened] = useState(true);
  const [notifySignalsClosed, setNotifySignalsClosed] = useState(true);
  const [notifyErrors, setNotifyErrors] = useState(true);
  const [notifyServiceDown, setNotifyServiceDown] = useState(true);
  const [notifySyncLag, setNotifySyncLag] = useState(true);
  const [notifyErrorSpike, setNotifyErrorSpike] = useState(true);
  const [notifyDdBreach, setNotifyDdBreach] = useState(true);
  const [notifyKillSwitch, setNotifyKillSwitch] = useState(true);

  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  const load = async () => {
    try {
      const res = await fetchTelegramSettings();
      const s = res?.settings || {};
      setEnabled(Boolean(s.enabled ?? true));
      setChatId(String(s.chat_id || ""));
      setPatcherSettingsKey(String(s.patcher_settings_key || ""));
      setHasToken(Boolean(s.has_token));
      setBotToken("");

      setNotifySignalsCreated(Boolean(s.notify_signals_created ?? true));
      setNotifySignalsApproved(Boolean(s.notify_signals_approved ?? true));
      setNotifySignalsOpened(Boolean(s.notify_signals_opened ?? true));
      setNotifySignalsClosed(Boolean(s.notify_signals_closed ?? true));
      setNotifyErrors(Boolean(s.notify_errors ?? true));
      setNotifyServiceDown(Boolean(s.notify_service_down ?? true));
      setNotifySyncLag(Boolean(s.notify_sync_lag ?? true));
      setNotifyErrorSpike(Boolean(s.notify_error_spike ?? true));
      setNotifyDdBreach(Boolean(s.notify_dd_breach ?? true));
      setNotifyKillSwitch(Boolean(s.notify_kill_switch ?? true));
      setMessage("");
    } catch (err: any) {
      setMessage(err?.message || "Failed to load notification settings.");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const save = async () => {
    setBusy(true);
    try {
      await updateTelegramSettings({
        enabled,
        chat_id: chatId,
        bot_token: botToken,
        patcher_settings_key: patcherSettingsKey,
        notify_signals_created: notifySignalsCreated,
        notify_signals_approved: notifySignalsApproved,
        notify_signals_opened: notifySignalsOpened,
        notify_signals_closed: notifySignalsClosed,
        notify_errors: notifyErrors,
        notify_service_down: notifyServiceDown,
        notify_sync_lag: notifySyncLag,
        notify_error_spike: notifyErrorSpike,
        notify_dd_breach: notifyDdBreach,
        notify_kill_switch: notifyKillSwitch,
      });
      setBotToken("");
      setMessage("Notification settings saved.");
      await load();
    } catch (err: any) {
      setMessage(err?.message || "Failed to save settings.");
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async () => {
    setBusy(true);
    try {
      const out = await testTelegram();
      setMessage(out?.ok ? "Test message sent." : out?.error || "Test failed.");
    } catch (err: any) {
      setMessage(err?.message || "Test failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <SectionHeader
        title="Telegram Notifications"
        subtitle="Signals + errors notifications stored in Postgres settings through Gateway."
        right={message ? <span className="muted">{message}</span> : null}
      />

      <Panel title="Status">
        <div className="filters-row">
          <StatusPill text={enabled ? "Notifications Enabled" : "Notifications Disabled"} tone={enabled ? "good" : "warn"} />
          <StatusPill text={hasToken ? "Token configured" : "Token missing"} tone={hasToken ? "good" : "bad"} />
          <label className="muted" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            <input data-testid="alerts-enabled" type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            enabled
          </label>
        </div>
      </Panel>

      <Panel title="Telegram / Patcher Settings">
        <div className="grid-2">
          <label className="muted">
            Chat ID
            <input data-testid="alerts-chat-id" className="dark-input" value={chatId} onChange={(e) => setChatId(e.target.value)} />
          </label>
          <label className="muted">
            Bot Token (leave empty to keep existing)
            <input
              data-testid="alerts-bot-token"
              className="dark-input"
              type="password"
              value={botToken}
              onChange={(e) => setBotToken(e.target.value)}
              autoComplete="new-password"
            />
          </label>
          <label className="muted" style={{ gridColumn: "1 / -1" }}>
            Patcher Integration Key (optional)
            <input
              data-testid="alerts-patcher-key"
              className="dark-input"
              value={patcherSettingsKey}
              onChange={(e) => setPatcherSettingsKey(e.target.value)}
              placeholder="patcher.py settings key"
            />
          </label>
        </div>
      </Panel>

      <Panel title="Event Toggles">
        <div className="filters-row">
          <label className="muted">
            <input type="checkbox" checked={notifySignalsCreated} onChange={(e) => setNotifySignalsCreated(e.target.checked)} /> Signals Created
          </label>
          <label className="muted">
            <input type="checkbox" checked={notifySignalsApproved} onChange={(e) => setNotifySignalsApproved(e.target.checked)} /> Signals Approved
          </label>
          <label className="muted">
            <input type="checkbox" checked={notifySignalsOpened} onChange={(e) => setNotifySignalsOpened(e.target.checked)} /> Signals Opened
          </label>
          <label className="muted">
            <input type="checkbox" checked={notifySignalsClosed} onChange={(e) => setNotifySignalsClosed(e.target.checked)} /> Signals Closed
          </label>
          <label className="muted">
            <input type="checkbox" checked={notifyErrors} onChange={(e) => setNotifyErrors(e.target.checked)} /> Errors Detected
          </label>
          <label className="muted">
            <input type="checkbox" checked={notifyServiceDown} onChange={(e) => setNotifyServiceDown(e.target.checked)} /> Service Down
          </label>
          <label className="muted">
            <input type="checkbox" checked={notifySyncLag} onChange={(e) => setNotifySyncLag(e.target.checked)} /> Sync Lag
          </label>
          <label className="muted">
            <input type="checkbox" checked={notifyErrorSpike} onChange={(e) => setNotifyErrorSpike(e.target.checked)} /> Error Spike
          </label>
          <label className="muted">
            <input type="checkbox" checked={notifyDdBreach} onChange={(e) => setNotifyDdBreach(e.target.checked)} /> Drawdown Breach
          </label>
          <label className="muted">
            <input type="checkbox" checked={notifyKillSwitch} onChange={(e) => setNotifyKillSwitch(e.target.checked)} /> Kill Switch Triggered
          </label>
        </div>
      </Panel>

      <Panel title="Actions">
        <div className="filters-row">
          <button data-testid="alerts-save" className="action-btn primary" disabled={busy} onClick={() => void save()}>
            Save Settings
          </button>
          <button data-testid="alerts-test" className="action-btn" disabled={busy} onClick={() => void sendTest()}>
            Send Test Message
          </button>
          <button data-testid="alerts-refresh" className="action-btn" disabled={busy} onClick={() => void load()}>
            Refresh
          </button>
        </div>
      </Panel>
    </div>
  );
}
