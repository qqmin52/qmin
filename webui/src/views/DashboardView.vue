<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { UnauthorizedError, fetchStatus } from "../api";
import type { StatusResponse } from "../types";

const emit = defineEmits<{ unauthorized: [] }>();

const status = ref<StatusResponse | null>(null);
const error = ref("");
let timer: ReturnType<typeof setInterval> | undefined;

const connected = computed(() => status.value?.connected ?? false);
const uptimeText = computed(() =>
  formatUptime(status.value?.uptime_seconds ?? 0),
);
const pluginText = computed(() => {
  if (!status.value) {
    return "-";
  }
  return `${status.value.plugin_enabled}/${status.value.plugin_total}`;
});
const pluginLoadedText = computed(() =>
  status.value ? `已加载 ${status.value.plugin_loaded}` : "-",
);
const logCountText = computed(() =>
  status.value ? String(status.value.log_count) : "-",
);

function formatUptime(totalSeconds: number): string {
  const total = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}s`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

async function load(): Promise<void> {
  try {
    status.value = await fetchStatus();
    error.value = "";
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      emit("unauthorized");
      return;
    }
    error.value = err instanceof Error ? err.message : String(err);
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
  <div>
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
      class="alert"
    />
    <div class="cards">
      <el-card>
        <template #header>连接状态</template>
        <el-tag :type="connected ? 'success' : 'info'">
          {{ connected ? "在线" : "离线" }}
        </el-tag>
      </el-card>
      <el-card>
        <template #header>运行时长</template>
        <p class="value">{{ uptimeText }}</p>
      </el-card>
      <el-card>
        <template #header>插件</template>
        <p class="value">{{ pluginText }}</p>
        <p class="sub">{{ pluginLoadedText }}</p>
      </el-card>
      <el-card>
        <template #header>日志条数</template>
        <p class="value">{{ logCountText }}</p>
      </el-card>
    </div>
  </div>
</template>

<style scoped>
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
}

.alert {
  margin-bottom: 16px;
}

.value {
  margin: 0;
  font-size: 22px;
  font-variant-numeric: tabular-nums;
}

.sub {
  margin: 6px 0 0;
  color: #909399;
  font-size: 12px;
}

@media (max-width: 600px) {
  .cards {
    grid-template-columns: 1fr;
  }
}
</style>
