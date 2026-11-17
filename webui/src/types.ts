export type LogLevel = "DEBUG" | "INFO" | "WARNING" | "ERROR";

export interface StatusResponse {
  connected: boolean;
  started_at: string | null;
  uptime_seconds: number;
  plugin_total: number;
  plugin_enabled: number;
  plugin_loaded: number;
  log_count: number;
}

export interface LogItem {
  seq: number;
  time: string;
  level: LogLevel;
  source: string;
  message: string;
}

export interface LogsResponse {
  items: LogItem[];
  total: number;
  latest_seq: number;
  buffer_total: number;
}

export interface PluginInfo {
  name: string;
  enabled: boolean;
  loaded: boolean;
  handler_count: number;
  error: string | null;
  display_name: string | null;
  description: string | null;
  version: string | null;
}

export interface InstallPluginRequest {
  name: string;
  code: string;
  overwrite?: boolean;
}

export interface PluginListResponse {
  items: PluginInfo[];
  total: number;
}

export interface ConfigOut {
  app_id: string;
  app_secret: string;
  host: string;
  port: number;
  log_level: string;
  db_path: string;
  admin_token_set: boolean;
}

export interface ConfigUpdateRequest {
  app_id?: string;
  app_secret?: string;
  host?: string;
  port?: number;
  log_level?: string;
  db_path?: string;
}

export interface SetupStatusResponse {
  configured: boolean;
  missing: string[];
}

export interface SetupRequest {
  app_id: string;
  app_secret: string;
}

export interface SetupResponse {
  configured: boolean;
  admin_token: string | null;
  token_already_existed: boolean;
  restart_required: boolean;
}

export interface BotStatusResponse {
  running: boolean;
}

export interface BotActionResult {
  started: boolean;
  error: string | null;
}
