import type {
  BotActionResult,
  BotStatusResponse,
  ConfigOut,
  ConfigUpdateRequest,
  InstallPluginRequest,
  LogsResponse,
  PluginInfo,
  PluginListResponse,
  SetupRequest,
  SetupResponse,
  SetupStatusResponse,
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

/** 带状态码与错误码的接口异常，便于页面展示后端的具体原因。 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function readErrorPayload(
  response: Response,
): Promise<{ code: string; detail: string }> {
  try {
    const data = (await response.json()) as {
      code?: unknown;
      detail?: unknown;
    };
    return {
      code: typeof data.code === "string" ? data.code : "",
      detail: typeof data.detail === "string" ? data.detail : "",
    };
  } catch {
    return { code: "", detail: "" };
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

export interface FetchLogsParams {
  after_seq?: number;
  before_seq?: number;
  limit?: number;
  level?: string;
  source?: string;
  q?: string;
}

export async function fetchLogs(
  params: FetchLogsParams = {},
): Promise<LogsResponse> {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? 200));
  query.set("after_seq", String(params.after_seq ?? 0));
  if (params.before_seq !== undefined) {
    query.set("before_seq", String(params.before_seq));
  }
  if (params.level) {
    query.set("level", params.level);
  }
  if (params.source) {
    query.set("source", params.source);
  }
  if (params.q) {
    query.set("q", params.q);
  }
  return apiGet<LogsResponse>(`/api/logs?${query.toString()}`);
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

export async function installPlugin(
  payload: InstallPluginRequest,
): Promise<PluginInfo> {
  const response = await fetch("/api/plugins/install", {
    method: "POST",
    headers: {
      "X-Admin-Token": getToken(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (response.status === 401) {
    throw new UnauthorizedError();
  }
  if (!response.ok) {
    const { code, detail } = await readErrorPayload(response);
    const fallback =
      code === "plugin_exists"
        ? "同名插件已存在，请先删除或改名"
        : `HTTP ${response.status}`;
    throw new ApiError(response.status, detail || fallback);
  }
  return (await response.json()) as PluginInfo;
}

export async function reloadPlugin(name: string): Promise<PluginInfo> {
  return apiSend<PluginInfo>(
    "POST",
    `/api/plugins/${encodeURIComponent(name)}/reload`,
    {},
  );
}

export async function deletePlugin(name: string): Promise<{ removed: boolean }> {
  const response = await fetch(`/api/plugins/${encodeURIComponent(name)}`, {
    method: "DELETE",
    headers: { "X-Admin-Token": getToken() },
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
  return (await response.json()) as { removed: boolean };
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

// ---------------------------------------------------------------- setup
// 以下两个接口不需要鉴权（用户还没有管理令牌）

async function apiGetPublic<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

async function apiPostPublic<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (response.status === 403) {
    throw new Error("already_configured");
  }
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchSetupStatus(): Promise<SetupStatusResponse> {
  return apiGetPublic<SetupStatusResponse>("/api/setup/status");
}

export async function completeSetup(
  payload: SetupRequest,
): Promise<SetupResponse> {
  return apiPostPublic<SetupResponse>("/api/setup", payload);
}

// ---------------------------------------------------------------- bot

export async function fetchBotStatus(): Promise<BotStatusResponse> {
  return apiGet<BotStatusResponse>("/api/bot");
}

export async function startBot(): Promise<BotActionResult> {
  return apiSend<BotActionResult>("POST", "/api/bot/start", {});
}

export async function stopBot(): Promise<BotActionResult> {
  return apiSend<BotActionResult>("POST", "/api/bot/stop", {});
}
