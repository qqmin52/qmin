import type {
  ConfigOut,
  ConfigUpdateRequest,
  LogsResponse,
  PluginInfo,
  PluginListResponse,
  StatusResponse,
} from "./types";

export const TOKEN_KEY = "qmin_admin_token";

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export class UnauthorizedError extends Error {
  constructor(message = "unauthorized") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

export class NotFoundError extends Error {
  constructor(message = "not found") {
    super(message);
    this.name = "NotFoundError";
  }
}

async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    headers: { "X-Admin-Token": getToken() },
  });
  if (response.status === 401) {
    throw new UnauthorizedError();
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchStatus(): Promise<StatusResponse> {
  return apiGet<StatusResponse>("/api/status");
}

export async function fetchLogs(
  afterSeq: number,
  limit = 200,
): Promise<LogsResponse> {
  return apiGet<LogsResponse>(
    `/api/logs?limit=${limit}&after_seq=${afterSeq}`,
  );
}

async function apiSend<T>(
  method: "POST" | "PUT",
  path: string,
  body: unknown,
): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: {
      "X-Admin-Token": getToken(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (response.status === 401) {
    throw new UnauthorizedError();
  }
  if (response.status === 404) {
    throw new NotFoundError();
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchPlugins(): Promise<PluginListResponse> {
  return apiGet<PluginListResponse>("/api/plugins");
}

export async function togglePlugin(
  name: string,
  enabled: boolean,
): Promise<PluginInfo> {
  return apiSend<PluginInfo>(
    "POST",
    `/api/plugins/${encodeURIComponent(name)}/toggle`,
    { enabled },
  );
}

export async function fetchConfig(): Promise<ConfigOut> {
  return apiGet<ConfigOut>("/api/config");
}

export async function updateConfig(
  payload: ConfigUpdateRequest,
): Promise<{ saved: boolean; restart_required: boolean }> {
  return apiSend<{ saved: boolean; restart_required: boolean }>(
    "PUT",
    "/api/config",
    payload,
  );
}
