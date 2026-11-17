<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { UnauthorizedError, fetchLogs } from "../api";
import type { LogItem } from "../types";
import EmptyState from "../components/EmptyState.vue";
import Icon from "../components/Icon.vue";
import SectionCard from "../components/SectionCard.vue";

const emit = defineEmits<{ unauthorized: [] }>();

const MAX_ITEMS = 500;
const PAGE_SIZE = 200;

const items = ref<LogItem[]>([]);
const latestSeq = ref(0);
const paused = ref(false);
const autoScroll = computed(() => !paused.value);
const error = ref("");
const tableRef = ref<{ setScrollTop: (top: number) => void } | null>(null);
let timer: ReturnType<typeof setInterval> | undefined;
// 防抖：同一次 load 内只重置一次，避免 fetchLogs(0) 再次触发重置
let resetting = false;

// 筛选条件
const levelFilter = ref<string>("");
const sourceFilter = ref("");
const keyword = ref("");
let filterTimer: ReturnType<typeof setTimeout> | undefined;

// 是否还有更早的日志
const hasMore = ref(false);
const loadingEarlier = ref(false);

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function levelClass(level: string): string {
  return `q-pill q-pill--${level.toLowerCase()}`;
}

function filterParams(): {
  level?: string;
  source?: string;
  q?: string;
} {
  return {
    level: levelFilter.value || undefined,
    source: sourceFilter.value.trim() || undefined,
    q: keyword.value.trim() || undefined,
  };
}

async function scrollToBottom(): Promise<void> {
  if (!autoScroll.value) {
    return;
  }
  await nextTick();
  tableRef.value?.setScrollTop(Number.MAX_SAFE_INTEGER);
}

/** 首屏 / 筛选变化后：清空并拉取最新一页。 */
async function loadLatest(): Promise<void> {
  latestSeq.value = 0;
  items.value = [];
  const response = await fetchLogs({
    after_seq: 0,
    limit: PAGE_SIZE,
    ...filterParams(),
  });
  latestSeq.value = response.latest_seq;
  items.value = response.items.slice(-MAX_ITEMS);
  hasMore.value = response.items.length >= PAGE_SIZE;
  error.value = "";
  await scrollToBottom();
}

async function load(): Promise<void> {
  try {
    const response = await fetchLogs({
      after_seq: latestSeq.value,
      limit: PAGE_SIZE,
      ...filterParams(),
    });

    // 服务端 seq 重置后 latest_seq 会变小——这是唯一可靠的重启信号。
    // 不管本次 after_seq 请求返回的 items 是否为空（after_seq 可能大于新 latest_seq），
    // 只要 latest_seq 变小就判定服务端已重置。
    if (response.latest_seq < latestSeq.value && !resetting) {
      resetting = true;
      try {
        await loadLatest();
      } finally {
        resetting = false;
      }
      return;
    }

    latestSeq.value = response.latest_seq;
    if (response.items.length > 0) {
      items.value = items.value
        .concat(response.items)
        .slice(-MAX_ITEMS);
      error.value = "";
      await scrollToBottom();
    }
  } catch (err) {
    resetting = false;
    if (err instanceof UnauthorizedError) {
      emit("unauthorized");
      return;
    }
    error.value = err instanceof Error ? err.message : String(err);
  }
}

/** 加载更早一页：用当前首条 seq 作为 before_seq。不触发自动滚动。 */
async function loadEarlier(): Promise<void> {
  const first = items.value[0];
  if (first === undefined || loadingEarlier.value) {
    return;
  }
  loadingEarlier.value = true;
  try {
    const response = await fetchLogs({
      before_seq: first.seq,
      limit: PAGE_SIZE,
      ...filterParams(),
    });
    if (response.items.length > 0) {
      items.value = response.items.concat(items.value);
      error.value = "";
    }
    hasMore.value = response.items.length >= PAGE_SIZE;
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      emit("unauthorized");
      return;
    }
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loadingEarlier.value = false;
  }
}

async function reload(): Promise<void> {
  try {
    await loadLatest();
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      emit("unauthorized");
      return;
    }
    error.value = err instanceof Error ? err.message : String(err);
  }
}

function scheduleReload(): void {
  if (filterTimer !== undefined) {
    clearTimeout(filterTimer);
  }
  filterTimer = setTimeout(() => {
    void reload();
  }, 300);
}

watch([levelFilter, sourceFilter, keyword], scheduleReload);

onMounted(() => {
  void reload();
  timer = setInterval(() => {
    void load();
  }, 1000);
});

onUnmounted(() => {
  if (timer !== undefined) {
    clearInterval(timer);
    timer = undefined;
  }
  if (filterTimer !== undefined) {
    clearTimeout(filterTimer);
    filterTimer = undefined;
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
    />

    <SectionCard title="日志记录" description="每秒自动拉取新日志">
      <div class="toolbar">
        <div class="filters">
          <el-select
            v-model="levelFilter"
            placeholder="全部级别"
            clearable
            class="level-select"
          >
            <el-option label="全部级别" value="" />
            <el-option label="INFO" value="INFO" />
            <el-option label="WARNING" value="WARNING" />
            <el-option label="ERROR" value="ERROR" />
          </el-select>
          <el-input
            v-model="sourceFilter"
            placeholder="来源（如 bot）"
            clearable
            class="source-input"
          />
          <el-input
            v-model="keyword"
            placeholder="关键词搜索"
            clearable
            class="keyword-input"
          />
        </div>
        <div class="tools">
          <el-checkbox v-model="paused">暂停滚动</el-checkbox>
          <el-button @click="reload">
            <Icon name="refresh" :size="15" class="btn-icon" />
            刷新
          </el-button>
        </div>
      </div>

      <el-table
        ref="tableRef"
        :data="items"
        height="480"
        stripe
        :row-style="{ height: '44px' }"
      >
        <el-table-column label="时间" width="100">
          <template #default="scope">
            <span class="q-mono time">{{ formatTime(scope.row.time) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="级别" width="100">
          <template #default="scope">
            <span :class="levelClass(scope.row.level)">
              {{ scope.row.level }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="source" label="来源" width="140" />
        <el-table-column prop="message" label="内容" min-width="240" />
        <template #empty>
          <EmptyState
            title="暂无日志"
            description="启动机器人后，连接和消息记录会出现在这里"
          />
        </template>
      </el-table>

      <div v-if="hasMore" class="footer">
        <el-button :loading="loadingEarlier" @click="loadEarlier">
          加载更早
        </el-button>
      </div>
    </SectionCard>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: var(--q-space-4);
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--q-space-3);
  margin-bottom: var(--q-space-4);
  flex-wrap: wrap;
}

.filters {
  display: flex;
  align-items: center;
  gap: var(--q-space-3);
  flex-wrap: wrap;
  min-width: 0;
}

.level-select {
  width: 140px;
  flex: none;
}

.source-input {
  width: 180px;
  flex: none;
}

.keyword-input {
  width: 220px;
  flex: none;
}

.tools {
  display: flex;
  align-items: center;
  gap: var(--q-space-3);
  flex: none;
}

.btn-icon {
  margin-right: 6px;
}

.time {
  font-size: var(--q-font-12);
  color: var(--q-text-2);
}

.footer {
  display: flex;
  justify-content: center;
  margin-top: var(--q-space-4);
}

@media (max-width: 640px) {
  .level-select,
  .source-input,
  .keyword-input {
    width: 100%;
  }

  .filters,
  .tools {
    width: 100%;
  }
}
</style>
