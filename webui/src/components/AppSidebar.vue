<script setup lang="ts">
import Icon from "./Icon.vue";

type ViewName = "dashboard" | "logs" | "plugins" | "settings";

defineProps<{ active: ViewName }>();
const emit = defineEmits<{ "update:active": [view: ViewName] }>();

const items: { key: ViewName; label: string }[] = [
  { key: "dashboard", label: "仪表盘" },
  { key: "logs", label: "日志" },
  { key: "plugins", label: "插件" },
  { key: "settings", label: "设置" },
];

const VERSION = "v0.1.0";
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="mark">Q</div>
      <div class="brand-text">
        <p class="name">Qmin</p>
        <p class="sub">QQ 官方机器人框架</p>
      </div>
    </div>

    <nav class="nav">
      <button
        v-for="item in items"
        :key="item.key"
        type="button"
        class="nav-item"
        :class="{ active: active === item.key }"
        :title="item.label"
        @click="emit('update:active', item.key)"
      >
        <Icon :name="item.key" :size="20" />
        <span class="nav-label">{{ item.label }}</span>
      </button>
    </nav>

    <div class="version">{{ VERSION }}</div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 220px;
  flex: none;
  height: 100vh;
  position: sticky;
  top: 0;
  display: flex;
  flex-direction: column;
  background: var(--q-surface);
  border-right: 1px solid var(--q-border);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--q-space-3);
  height: 56px;
  padding: 0 var(--q-space-4);
  border-bottom: 1px solid var(--q-border);
  flex: none;
}

.mark {
  width: 28px;
  height: 28px;
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--q-radius-sm);
  background: var(--q-primary);
  color: var(--q-surface);
  font-size: var(--q-font-14);
  font-weight: 600;
}

.brand-text {
  min-width: 0;
}

.name {
  font-size: var(--q-font-20);
  font-weight: 600;
  line-height: 1.2;
  color: var(--q-text);
}

.sub {
  font-size: var(--q-font-12);
  color: var(--q-text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--q-space-3) var(--q-space-2);
  flex: 1;
  min-height: 0;
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--q-space-3);
  height: 40px;
  padding: 0 var(--q-space-3);
  border: none;
  border-radius: var(--q-radius-sm);
  background: transparent;
  color: var(--q-text-2);
  font-size: var(--q-font-14);
  font-family: inherit;
  cursor: pointer;
  transition: background-color 0.15s ease, color 0.15s ease;
  white-space: nowrap;
}

.nav-item:hover {
  background: var(--q-bg);
  color: var(--q-text);
}

.nav-item.active {
  background: var(--q-primary-soft);
  color: var(--q-primary);
  font-weight: 500;
}

.nav-item.active::before {
  content: "";
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 999px;
  background: var(--q-primary);
}

.version {
  padding: var(--q-space-3) var(--q-space-4);
  border-top: 1px solid var(--q-border);
  font-size: var(--q-font-12);
  color: var(--q-text-3);
  flex: none;
}

/* <1100px：收成 64px，只留图标 */
@media (max-width: 1100px) {
  .sidebar {
    width: 64px;
  }

  .brand {
    justify-content: center;
    padding: 0;
  }

  .brand-text,
  .nav-label,
  .version {
    display: none;
  }

  .nav {
    padding: var(--q-space-3) var(--q-space-2);
    align-items: center;
  }

  .nav-item {
    justify-content: center;
    padding: 0;
    width: 40px;
  }
}

/* <900px：变为顶部横向导航条 */
@media (max-width: 900px) {
  .sidebar {
    width: 100%;
    height: 56px;
    position: sticky;
    top: 0;
    z-index: 20;
    flex-direction: row;
    align-items: center;
    border-right: none;
    border-bottom: 1px solid var(--q-border);
  }

  .brand {
    width: 56px;
    height: 56px;
    padding: 0;
    border-bottom: none;
    justify-content: center;
    flex: none;
  }

  .nav {
    flex-direction: row;
    align-items: center;
    gap: var(--q-space-1);
    padding: 0 var(--q-space-2);
    overflow-x: auto;
  }

  .nav-item {
    width: auto;
    height: 36px;
    padding: 0 var(--q-space-3);
  }

  .nav-label {
    display: inline;
  }

  .nav-item.active::before {
    left: 8px;
    right: 8px;
    top: auto;
    bottom: 0;
    width: auto;
    height: 2px;
  }
}
</style>
