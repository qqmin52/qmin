<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
}>();
</script>

<template>
  <div class="empty">
    <svg
      class="icon"
      width="40"
      height="40"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 10h18M8 15h4" />
    </svg>
    <p class="title">{{ title }}</p>
    <p v-if="description" class="desc">{{ description }}</p>
    <div v-if="$slots.default" class="actions">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--q-space-2);
  padding: 40px var(--q-space-4);
  text-align: center;
}

.icon {
  color: var(--q-text-3);
  margin-bottom: var(--q-space-1);
}

.title {
  font-size: var(--q-font-14);
  font-weight: 500;
  color: var(--q-text);
}

.desc {
  font-size: var(--q-font-13);
  color: var(--q-text-2);
  max-width: 360px;
}

.actions {
  margin-top: var(--q-space-2);
}
</style>
