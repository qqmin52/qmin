import { computed, ref } from "vue";
import {
  UnauthorizedError,
  fetchBotStatus,
  fetchStatus,
  startBot,
  stopBot,
} from "../api";

/**
 * 机器人启停状态（模块级单例）。
 *
 * App.vue 顶栏与仪表盘共用同一份状态，避免两处各自请求导致显示不一致。
 */
const running = ref<boolean | null>(null); // null 表示当前模式不支持手动启停
const connected = ref(false);
const busy = ref(false);
const error = ref("");

let pollTimer: ReturnType<typeof setInterval> | undefined;
let subscribers = 0;

const badgeStatus = computed<"online" | "offline" | "connecting">(() => {
  if (running.value === null) {
    return connected.value ? "online" : "offline";
  }
  if (running.value && connected.value) {
    return "online";
  }
  if (running.value) {
    return "connecting";
  }
  return "offline";
});

const unsupported = computed(() => running.value === null);
const needsSetup = computed(() => error.value.includes("凭证未配置"));

function isNotFoundMode(message: string): boolean {
  return message === "HTTP 409";
}

async function refresh(): Promise<void> {
  const status = await fetchStatus();
  connected.value = status.connected;
  try {
    const resp = await fetchBotStatus();
    running.value = resp.running;
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      throw err;
    }
    if (err instanceof Error && isNotFoundMode(err.message)) {
      running.value = null;
      return;
    }
    throw err;
  }
}

async function toggle(): Promise<void> {
  if (busy.value || running.value === null) {
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    const result = running.value ? await stopBot() : await startBot();
    if (result.error) {
      error.value = result.error;
    }
    await refresh();
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      throw err;
    }
    if (err instanceof Error && isNotFoundMode(err.message)) {
      running.value = null;
      return;
    }
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    busy.value = false;
  }
}

async function pollOnce(): Promise<void> {
  try {
    await refresh();
    error.value = "";
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      stopPolling();
      throw err;
    }
    error.value = err instanceof Error ? err.message : String(err);
  }
}

/** 顶栏挂载时开始轮询，卸载时停止（按订阅计数）。 */
function startPolling(intervalMs = 2000): void {
  subscribers += 1;
  if (pollTimer === undefined) {
    pollTimer = setInterval(() => {
      void pollOnce();
    }, intervalMs);
  }
}

function stopPolling(): void {
  subscribers = Math.max(0, subscribers - 1);
  if (subscribers === 0 && pollTimer !== undefined) {
    clearInterval(pollTimer);
    pollTimer = undefined;
  }
}

export function useBotControl() {
  return {
    running,
    connected,
    busy,
    error,
    badgeStatus,
    unsupported,
    needsSetup,
    refresh,
    toggle,
    startPolling,
    stopPolling,
  };
}
