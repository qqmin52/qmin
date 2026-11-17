<script setup lang="ts">
defineProps<{
  title: string;
  description?: string;
}>();
</script>

<template>
  <section class="card">
    <header class="header">
      <div class="titles">
        <h2 class="title">{{ title }}</h2>
        <p v-if="description" class="desc">{{ description }}</p>
      </div>
      <div v-if="$slots.actions" class="actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.card {
  background: var(--q-surface);
  border: 1px solid var(--q-border);
  border-radius: var(--q-radius);
  box-shadow: var(--q-shadow-sm);
  overflow: hidden;
}

.header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--q-space-4);
  padding: var(--q-space-4) var(--q-space-5);
  border-bottom: 1px solid var(--q-border);
}

.titles {
  min-width: 0;
}

.title {
  font-size: var(--q-font-14);
  font-weight: 600;
  color: var(--q-text);
}

.desc {
  margin-top: 2px;
  font-size: var(--q-font-12);
  color: var(--q-text-2);
}

.actions {
  display: flex;
  align-items: center;
  gap: var(--q-space-2);
  flex: none;
}

.body {
  padding: var(--q-space-5);
}
</style>
