import { api } from "./client";

export type AuthStatus = {
  ok?: boolean;
  enabled: boolean;
  required: boolean;
  authenticated: boolean;
  method: string;
};

export async function fetchAuthStatus(): Promise<AuthStatus> {
  const { data } = await api.get<AuthStatus>("/auth/status");
  return data;
}

export async function loginAuth(apiKey: string): Promise<{ ok: boolean; message?: string; enabled?: boolean }> {
  const { data } = await api.post("/auth/login", { api_key: apiKey });
  return data;
}

export async function logoutAuth(): Promise<{ ok: boolean; message?: string }> {
  const { data } = await api.post("/auth/logout", {});
  return data;
}
