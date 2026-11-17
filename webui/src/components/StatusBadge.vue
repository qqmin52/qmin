<script setup lang="ts">
import { computed } from "vue";

type BadgeStatus = "online" | "offline" | "connecting";

const props = defineProps<{ status: BadgeStatus }>();

const label = computed(() => {
  switch (props.status) {
    case "online":
      return "在线";
    case "connecting":
      return "连接中";
    default:
      return "离线";
  }
});
</script>

<template>
  <span class="badge" :class="status">
    <span class="dot" />
    <span class="label">{{ label }}</span>
  </span>
</template>

<style scoped>
.badge {
  display: inline-flex;
  align-items: center;
  gap: var(--q-space-2);
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--q-border);
  background: var(--q-surface);
  font-size: var(--q-font-12);
  color: var(--q-text-2);
  white-space: nowrap;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--q-text-3);
}

.online {
  color: var(--q-success);
  border-color: color-mix(in srgb, var(--q-success) 24%, var(--q-surface));
  background: color-mix(in srgb, var(--q-success) 8%, var(--q-surface));
}

.online .dot {
  background: var(--q-success);
}

.connecting {
  color: var(--q-primary);
  border-color: color-mix(in srgb, var(--q-primary) 24%, var(--q-surface));
  background: var(--q-primary-soft);
}

.connecting .dot {
  background: var(--q-primary);
  animation: q-pulse 1.4s ease-in-out infinite;
}

@keyframes q-pulse {
  0%,
  100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.35;
    transform: scale(0.82);
  }
}
</style>
