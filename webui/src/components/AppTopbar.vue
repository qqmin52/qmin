<script setup lang="ts">
import { onMounted, onUnmounted } from "vue";
import Icon from "./Icon.vue";
import StatusBadge from "./StatusBadge.vue";
import { useBotControl } from "../composables/useBotControl";

defineProps<{
  title: string;
  subtitle: string;
}>();

const emit = defineEmits<{
  editToken: [];
  logout: [];
  unauthorized: [];
}>();

const {
  running,
  busy,
  error: botError,
  badgeStatus,
  unsupported,
  refresh,
  toggle,
  startPolling,
  stopPolling,
} = useBotControl();

async function handleToggle(): Promise<void> {
  try {
    await toggle();
  } catch {
    emit("unauthorized");
  }
}

function onCommand(command: string): void {
  if (command === "switch") {
    emit("editToken");
  } else if (command === "logout") {
    emit("logout");
  }
}

async function poll(): Promise<void> {
  try {
    await refresh();
  } catch {
    emit("unauthorized");
  }
}

onMounted(() => {
  void poll();
  startPolling();
  window.addEventListener("focus", poll);
});

onUnmounted(() => {
  stopPolling();
  window.removeEventListener("focus", poll);
});
</script>

<template>
  <header class="topbar">
    <div class="titles">
      <h1 class="title">{{ title }}</h1>
      <p class="subtitle">{{ subtitle }}</p>
    </div>

    <div class="actions">
      <span v-if="botError" class="bot-error" :title="botError">
        {{ botError }}
      </span>
      <StatusBadge :status="badgeStatus" />
      <el-button
        v-if="!unsupported"
        :type="running ? 'default' : 'primary'"
        :loading="busy"
        @click="handleToggle"
      >
        <Icon v-if="!running" name="power" :size="16" class="btn-icon" />
        {{ running ? "停止机器人" : "启动机器人" }}
      </el-button>
      <el-dropdown trigger="click" @command="onCommand">
        <el-button text>令牌</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="switch">切换令牌</el-dropdown-item>
            <el-dropdown-item command="logout">退出</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </header>
</template>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 15;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--q-space-4);
  height: 56px;
  padding: 0 var(--q-space-6);
  background: var(--q-surface);
  border-bottom: 1px solid var(--q-border);
}

.titles {
  min-width: 0;
}

.title {
  font-size: var(--q-font-16);
  font-weight: 600;
  line-height: 1.3;
  color: var(--q-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.subtitle {
  font-size: var(--q-font-12);
  color: var(--q-text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--q-space-3);
  flex: none;
}

.btn-icon {
  margin-right: 6px;
}

.bot-error {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--q-danger);
  font-size: var(--q-font-12);
}

@media (max-width: 900px) {
  .topbar {
    top: 56px;
    height: auto;
    min-height: 56px;
    padding: var(--q-space-2) var(--q-space-4);
    flex-wrap: wrap;
  }
}

@media (max-width: 640px) {
  .subtitle,
  .bot-error {
    display: none;
  }
}
</style>
