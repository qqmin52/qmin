<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  NotFoundError,
  UnauthorizedError,
  fetchPlugins,
  togglePlugin,
} from "../api";
import type { PluginInfo } from "../types";

const emit = defineEmits<{ unauthorized: [] }>();

const items = ref<PluginInfo[]>([]);
const loading = ref(false);
const busyName = ref("");
const error = ref("");

async function load(): Promise<void> {
  loading.value = true;
  try {
    const response = await fetchPlugins();
    items.value = response.items;
    error.value = "";
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      emit("unauthorized");
      return;
    }
    error.value = err instanceof Error ? err.message : String(err);
  } finally {
    loading.value = false;
  }
}

async function toggle(row: PluginInfo, enabled: boolean): Promise<void> {
  busyName.value = row.name;
  try {
    const updated = await togglePlugin(row.name, enabled);
    const index = items.value.findIndex((item) => item.name === row.name);
    if (index !== -1) {
      items.value[index] = updated;
    }
    if (updated.enabled && !updated.loaded) {
      ElMessage.warning(updated.error ?? "插件启用失败");
    } else {
      ElMessage.success(updated.enabled ? "已启用" : "已禁用");
    }
  } catch (err) {
    // 开关使用 :model-value 受控，失败时行数据未变，开关自然回到原值。
    if (err instanceof UnauthorizedError) {
      emit("unauthorized");
      return;
    }
    if (err instanceof NotFoundError) {
      ElMessage.error("插件不存在");
      return;
    }
    ElMessage.error(err instanceof Error ? err.message : String(err));
  } finally {
    busyName.value = "";
  }
}

function onSwitchChange(
  row: PluginInfo,
  value: string | number | boolean,
): void {
  void toggle(row, value === true);
}

onMounted(() => {
  void load();
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
      <span class="hint">修改后立即生效，无需重启</span>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <el-table v-loading="loading" :data="items" empty-text="暂无插件" stripe>
      <el-table-column prop="name" label="插件名" min-width="160" />
      <el-table-column label="启用" width="110">
        <template #default="scope">
          <el-switch
            :model-value="scope.row.enabled"
            :loading="busyName === scope.row.name"
            :disabled="busyName === scope.row.name"
            @change="
              (value: string | number | boolean) =>
                onSwitchChange(scope.row, value)
            "
          />
        </template>
      </el-table-column>
      <el-table-column label="已加载" width="110">
        <template #default="scope">
          <el-tag :type="scope.row.loaded ? 'success' : 'info'" size="small">
            {{ scope.row.loaded ? "已加载" : "未加载" }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="handler 数" width="120">
        <template #default="scope">
          {{ scope.row.enabled ? scope.row.handler_count : "—" }}
        </template>
      </el-table-column>
      <el-table-column label="错误" min-width="200">
        <template #default="scope">
          <span v-if="scope.row.error" class="error-text">
            {{ scope.row.error }}
          </span>
          <span v-else>—</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.alert {
  margin-bottom: 16px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.hint {
  color: #909399;
  font-size: 13px;
}

.error-text {
  color: #f56c6c;
  word-break: break-all;
}
</style>
