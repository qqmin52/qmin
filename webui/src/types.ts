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
}
