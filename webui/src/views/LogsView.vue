<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { UnauthorizedError, fetchLogs } from "../api";
import type { LogItem, LogLevel } from "../types";

const emit = defineEmits<{ unauthorized: [] }>();

const MAX_ITEMS = 500;

const items = ref<LogItem[]>([]);
const latestSeq = ref(0);
const paused = ref(false);
const autoScroll = computed(() => !paused.value);
const error = ref("");
const tableRef = ref<{ setScrollTop: (top: number) => void } | null>(null);
let timer: ReturnType<typeof setInterval> | undefined;

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function levelType(level: LogLevel): "info" | "primary" | "warning" | "danger" {
  switch (level) {
    case "DEBUG":
      return "info";
    case "WARNING":
      return "warning";
    case "ERROR":
      return "danger";
    default:
      return "primary";
  }
}

async function load(): Promise<void> {
  try {
    const response = await fetchLogs(latestSeq.value);
    latestSeq.value = response.latest_seq;
    if (response.items.length > 0) {
      items.value = items.value
        .concat(response.items)
        .slice(-MAX_ITEMS);
      error.value = "";
      if (autoScroll.value) {
        await nextTick();
        tableRef.value?.setScrollTop(Number.MAX_SAFE_INTEGER);
      }
    }
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
  }, 1000);
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
    <div class="toolbar">
      <el-checkbox v-model="paused">暂停滚动</el-checkbox>
    </div>
    <el-table
      ref="tableRef"
      :data="items"
      height="480"
      empty-text="暂无日志"
      stripe
    >
      <el-table-column label="时间" width="110">
        <template #default="scope">{{ formatTime(scope.row.time) }}</template>
      </el-table-column>
      <el-table-column label="级别" width="110">
        <template #default="scope">
          <el-tag :type="levelType(scope.row.level)" size="small">
            {{ scope.row.level }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="source" label="来源" width="160" />
      <el-table-column prop="message" label="内容" min-width="240" />
    </el-table>
  </div>
</template>

<style scoped>
.alert {
  margin-bottom: 16px;
}

.toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 12px;
}
</style>
