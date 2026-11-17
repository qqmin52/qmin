<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { UnauthorizedError, fetchLogs, fetchStatus } from "../api";
import type { LogItem, StatusResponse } from "../types";
import EmptyState from "../components/EmptyState.vue";
import Icon from "../components/Icon.vue";
import SectionCard from "../components/SectionCard.vue";
import { useBotControl } from "../composables/useBotControl";

const emit = defineEmits<{
  unauthorized: [];
  goSettings: [];
  goLogs: [];
}>();

const {
  running,
  busy: botBusy,
  error: botError,
  needsSetup,
  toggle,
} = useBotControl();

const status = ref<StatusResponse | null>(null);
const recentLogs = ref<LogItem[]>([]);
const error = ref("");
let timer: ReturnType<typeof setInterval> | undefined;

const connected = computed(() => status.value?.connected ?? false);
const uptimeText = computed(() =>
  formatUptime(status.value?.uptime_seconds ?? 0),
);
const pluginText = computed(() => {
  if (!status.value) return "-";
  return `${status.value.plugin_enabled}/${status.value.plugin_total}`;
});
const logCountText = computed(() =>
  status.value ? String(status.value.log_count) : "-",
);
const modeText = computed(() =>
  running.value === null ? "不支持手动启停" : "qmin api",
);

// 未配置：从未连上、没有插件、也没有在运行
const unconfigured = computed(() => {
  if (!status.value) return false;
  return (
    !status.value.connected &&
    status.value.plugin_total === 0 &&
    running.value !== true
  );
});

function formatUptime(totalSeconds: number): string {
  const total = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString("zh-CN", { hour12: false });
}

function levelClass(level: string): string {
  return `q-pill q-pill--${level.toLowerCase()}`;
}

async function load(): Promise<void> {
  try {
    status.value = await fetchStatus();
    recentLogs.value = (await fetchLogs({ limit: 5 })).items;
    error.value = "";
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      emit("unauthorized");
      return;
    }
    error.value = err instanceof Error ? err.message : String(err);
  }
}

async function handleBotAction(): Promise<void> {
  try {
    await toggle();
    await load();
  } catch {
    emit("unauthorized");
  }
}

onMounted(() => {
  void load();
  timer = setInterval(() => {
    void load();
  }, 2000);
});

onUnmounted(() => {
  if (timer !== undefined) {
    clearInterval(timer);
    timer = undefined;
  }
});
</script>

<template>
  <div class="page">
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
      class="alert"
    />

    <SectionCard v-if="unconfigured" title="机器人状态">
      <EmptyState
        title="还没有连接机器人"
        description="填写 AppID 与 AppSecret 后，就能启动你的第一个 QQ 官方机器人。"
      >
        <el-button type="primary" @click="emit('goSettings')">
          去设置页填写
        </el-button>
      </EmptyState>
    </SectionCard>

    <template v-else>
      <!-- 主状态卡 -->
      <section class="hero">
        <div class="hero-main">
          <div class="hero-text">
            <p class="hero-status" :class="{ online: connected }">
              {{ connected ? "在线" : "离线" }}
            </p>
            <p class="hero-meta">
              运行时长 {{ uptimeText }}
              <span class="dot-sep">·</span>
              {{ modeText }}
            </p>
          </div>
          <div class="hero-actions">
            <p v-if="botError" class="bot-error">
              {{ botError }}
              <el-button
                v-if="needsSetup"
                link
                type="primary"
                @click="emit('goSettings')"
              >
                去设置页填写
              </el-button>
            </p>
            <el-button
              v-if="running !== null"
              :type="running ? 'default' : 'primary'"
              :loading="botBusy"
              @click="handleBotAction"
            >
              <Icon v-if="!running" name="power" :size="16" class="btn-icon" />
              {{ running ? "停止机器人" : "启动机器人" }}
            </el-button>
          </div>
        </div>
      </section>

      <!-- 三张小卡 -->
      <div class="stats">
        <SectionCard title="插件">
          <p class="stat-value">{{ pluginText }}</p>
          <p class="stat-sub">
            已加载 {{ status?.plugin_loaded ?? "-" }} 个
          </p>
        </SectionCard>
        <SectionCard title="日志条数">
          <p class="stat-value">{{ logCountText }}</p>
          <p class="stat-sub">最近 200 条内存缓冲</p>
        </SectionCard>
        <SectionCard title="当前模式">
          <p class="stat-mode">{{ modeText }}</p>
        </SectionCard>
      </div>

      <!-- 最近日志 -->
      <SectionCard title="最近日志">
        <template #actions>
          <el-button text type="primary" @click="emit('goLogs')">
            查看全部
          </el-button>
        </template>
        <div v-if="recentLogs.length === 0" class="logs-empty">
          暂无日志
        </div>
        <ul v-else class="log-list">
          <li v-for="item in recentLogs" :key="item.seq" class="log-row">
            <span class="log-time">{{ formatTime(item.time) }}</span>
            <span :class="levelClass(item.level)">{{ item.level }}</span>
            <span class="log-message" :title="item.message">
              {{ item.message }}
            </span>
          </li>
        </ul>
      </SectionCard>
    </template>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: var(--q-space-4);
}

.alert {
  margin-bottom: 0;
}

.hero {
  background: var(--q-surface);
  border: 1px solid var(--q-border);
  border-radius: var(--q-radius);
  box-shadow: var(--q-shadow-sm);
  padding: var(--q-space-5);
}

.hero-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--q-space-4);
  flex-wrap: wrap;
}

.hero-status {
  font-size: var(--q-font-20);
  font-weight: 600;
  color: var(--q-text-2);
  line-height: 1.3;
}

.hero-status.online {
  color: var(--q-success);
}

.hero-meta {
  margin-top: var(--q-space-1);
  font-size: var(--q-font-13);
  color: var(--q-text-2);
}

.dot-sep {
  margin: 0 var(--q-space-1);
  color: var(--q-text-3);
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: var(--q-space-3);
  flex-wrap: wrap;
}

.bot-error {
  color: var(--q-danger);
  font-size: var(--q-font-13);
  max-width: 420px;
}

.btn-icon {
  margin-right: 6px;
}

.stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--q-space-4);
}

.stat-value {
  font-size: var(--q-font-24);
  font-weight: 600;
  color: var(--q-text);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}

.stat-sub {
  margin-top: var(--q-space-1);
  font-size: var(--q-font-12);
  color: var(--q-text-2);
}

.stat-mode {
  font-size: var(--q-font-16);
  font-weight: 500;
  color: var(--q-text);
}

.logs-empty {
  padding: var(--q-space-4) 0;
  color: var(--q-text-2);
  font-size: var(--q-font-13);
}

.log-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.log-row {
  display: flex;
  align-items: center;
  gap: var(--q-space-3);
  height: 36px;
  border-bottom: 1px solid var(--q-border);
  min-width: 0;
}

.log-row:last-child {
  border-bottom: none;
}

.log-time {
  flex: none;
  width: 72px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--q-font-12);
  color: var(--q-text-2);
}

.log-message {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--q-text);
  font-size: var(--q-font-13);
}

@media (max-width: 900px) {
  .stats {
    grid-template-columns: 1fr;
  }
}
</style>
