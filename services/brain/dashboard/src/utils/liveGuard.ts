import { fetchLiveSafetyPolicy } from "../api/live";

export type LiveGuardPayload = {
  live_confirm: boolean;
  live_confirm_ack: boolean;
  live_pin?: string;
};

let cachedPolicy: any = null;
let cachedAt = 0;

async function getPolicy(force: boolean = false): Promise<any> {
  const now = Date.now();
  if (!force && cachedPolicy && now - cachedAt < 15_000) return cachedPolicy;
  const data = await fetchLiveSafetyPolicy(false);
  cachedPolicy = data?.policy || {};
  cachedAt = now;
  return cachedPolicy;
}

export async function requestLiveGuard(actionLabel: string, forcePolicyReload: boolean = false): Promise<LiveGuardPayload | null> {
  let policy: any = {};
  try {
    policy = await getPolicy(forcePolicyReload);
  } catch {
    policy = {};
  }

  const requireDouble = Boolean(policy?.double_confirm_required ?? true);
  const pinEnabled = Boolean(policy?.pin_enabled && policy?.has_pin);

  if (requireDouble) {
    const ok = window.confirm(`LIVE warning: ${actionLabel}. Continue?`);
    if (!ok) return null;
    const typed = (window.prompt("Type LIVE to confirm", "") || "").trim().toUpperCase();
    if (typed !== "LIVE") return null;
  }

  let livePin = "";
  if (pinEnabled) {
    livePin = (window.prompt("Enter LIVE safety PIN", "") || "").trim();
    if (!livePin) return null;
  }

  return {
    live_confirm: true,
    live_confirm_ack: true,
    ...(livePin ? { live_pin: livePin } : {}),
  };
}

export function clearLivePolicyCache() {
  cachedPolicy = null;
  cachedAt = 0;
}
