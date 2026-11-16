import type { LogsResponse, StatusResponse } from "./types";

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
