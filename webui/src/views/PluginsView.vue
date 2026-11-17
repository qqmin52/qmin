<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import {
  NotFoundError,
  UnauthorizedError,
  deletePlugin,
  fetchPlugins,
  installPlugin,
  reloadPlugin,
  togglePlugin,
} from "../api";
import type { PluginInfo } from "../types";
import EmptyState from "../components/EmptyState.vue";
import Icon from "../components/Icon.vue";
import SectionCard from "../components/SectionCard.vue";

const emit = defineEmits<{ unauthorized: [] }>();

const items = ref<PluginInfo[]>([]);
const loading = ref(false);
const busyName = ref("");
const error = ref("");

const dialogVisible = ref(false);
const submitting = ref(false);
const form = ref({ name: "", code: "" });
const templateHint = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);

const SAMPLE_PLUGIN = `"""示例插件：收到包含 hello 的群 @ 消息时回复。"""

from core.handlers import on_group_at

__plugin_name__ = "Hello 示例"
__description__ = "收到包含 hello 的群消息时回复一句问候"
__version__ = "1.0.0"


@on_group_at("hello")
async def hello(event) -> None:
    await event.reply("你好呀，我是 Qmin 插件")
`;

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

function replaceRow(updated: PluginInfo): void {
  const index = items.value.findIndex((item) => item.name === updated.name);
  if (index !== -1) {
    items.value[index] = updated;
  }
}

async function toggle(row: PluginInfo, enabled: boolean): Promise<void> {
  busyName.value = row.name;
  try {
    const updated = await togglePlugin(row.name, enabled);
    replaceRow(updated);
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

async function reload(row: PluginInfo): Promise<void> {
  busyName.value = row.name;
  try {
    const updated = await reloadPlugin(row.name);
    replaceRow(updated);
    if (updated.loaded) {
      ElMessage.success("已重新加载");
    } else {
      ElMessage.error(updated.error ?? "重新加载失败");
    }
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      emit("unauthorized");
      return;
    }
    if (err instanceof NotFoundError) {
      ElMessage.error("插件文件不存在");
      return;
    }
    ElMessage.error(err instanceof Error ? err.message : String(err));
  } finally {
    busyName.value = "";
  }
}

async function remove(row: PluginInfo): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `将删除 plugins/ 下的 ${row.name}.py 文件，删除后不可恢复，确定继续？`,
      "删除插件",
      {
        type: "warning",
        confirmButtonText: "删除",
        cancelButtonText: "取消",
      },
    );
  } catch {
    return;
  }
  try {
    await deletePlugin(row.name);
    items.value = items.value.filter((item) => item.name !== row.name);
    ElMessage.success("已删除");
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      emit("unauthorized");
      return;
    }
    if (err instanceof NotFoundError) {
      ElMessage.error("插件文件不存在，已刷新列表");
      await load();
      return;
    }
    ElMessage.error(err instanceof Error ? err.message : String(err));
  }
}

function openInstall(): void {
  form.value = { name: "", code: "" };
  templateHint.value = false;
  dialogVisible.value = true;
}

function fillTemplate(): void {
  form.value.code = SAMPLE_PLUGIN;
  if (!form.value.name) {
    form.value.name = "hello_demo";
  }
  templateHint.value = true;
}

function onFileChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) {
    return;
  }
  const base = file.name.replace(/\.py$/i, "");
  if (!form.value.name && /^[a-z][a-z0-9_]{0,63}$/.test(base)) {
    form.value.name = base;
  }
  const reader = new FileReader();
  reader.onload = () => {
    form.value.code = String(reader.result ?? "");
  };
  reader.onerror = () => {
    ElMessage.error("读取文件失败");
  };
  reader.readAsText(file, "utf-8");
  // 清空 value，允许重复选择同一个文件。
  input.value = "";
}

async function submit(): Promise<void> {
  const name = form.value.name.trim();
  if (!name || !form.value.code.trim()) {
    ElMessage.warning("插件名与代码不能为空");
    return;
  }
  submitting.value = true;
  try {
    const record = await installPlugin({ name, code: form.value.code });
    dialogVisible.value = false;
    await load();
    if (record.loaded) {
      ElMessage.success("已安装并加载");
    } else {
      ElMessage.error(record.error ?? "插件已写入，但加载失败");
    }
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      emit("unauthorized");
      return;
    }
    ElMessage.error(err instanceof Error ? err.message : String(err));
  } finally {
    submitting.value = false;
  }
}

function statusLabel(row: PluginInfo): string {
  if (!row.enabled) return "已禁用";
  return row.loaded ? "启用·已加载" : "启用·加载失败";
}

function statusType(row: PluginInfo): "success" | "danger" | "info" {
  if (!row.enabled) return "info";
  return row.loaded ? "success" : "danger";
}

function pluginTitle(row: PluginInfo): string {
  return row.display_name ?? row.name;
}

onMounted(() => {
  void load();
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

    <SectionCard title="插件" description="安装后立即生效，修改代码后可点「重新加载」">
      <template #actions>
        <el-button :loading="loading" @click="load">
          <Icon name="refresh" :size="15" class="btn-icon" />
          刷新
        </el-button>
        <el-button type="primary" @click="openInstall">安装插件</el-button>
      </template>

      <el-table v-loading="loading" :data="items" stripe>
        <el-table-column label="插件" min-width="180">
          <template #default="scope">
            <div class="plugin-cell">
              <span class="plugin-title">{{ pluginTitle(scope.row) }}</span>
              <span v-if="scope.row.display_name" class="plugin-sub">
                {{ scope.row.name }}
              </span>
              <span v-if="scope.row.version" class="plugin-sub">
                v{{ scope.row.version }}
              </span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="140">
          <template #default="scope">
            <el-tag :type="statusType(scope.row)" size="small">
              {{ statusLabel(scope.row) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="描述" min-width="240">
          <template #default="scope">
            <el-tooltip
              v-if="scope.row.error"
              :content="scope.row.error"
              placement="top"
            >
              <span class="error-text">{{ scope.row.error }}</span>
            </el-tooltip>
            <span v-else class="desc-text">
              {{ scope.row.description ?? "—" }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="处理器数" width="100" align="center">
          <template #default="scope">
            <span class="count-text">{{ scope.row.handler_count }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="240" align="right">
          <template #default="scope">
            <div class="row-actions">
              <el-switch
                :model-value="scope.row.enabled"
                :loading="busyName === scope.row.name"
                :disabled="busyName === scope.row.name"
                @change="
                  (value: string | number | boolean) =>
                    onSwitchChange(scope.row, value)
                "
              />
              <el-button
                link
                type="primary"
                :loading="busyName === scope.row.name"
                @click="reload(scope.row)"
              >
                重新加载
              </el-button>
              <el-button link type="danger" @click="remove(scope.row)">
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <EmptyState
            title="还没有安装任何插件"
            description="点击右上角「安装插件」粘贴代码，或把 .py 文件放进 plugins/ 后刷新"
          />
        </template>
      </el-table>
    </SectionCard>

    <el-dialog
      v-model="dialogVisible"
      title="安装插件"
      width="680px"
      :close-on-click-modal="false"
    >
      <div class="install-form">
        <el-input
          v-model="form.name"
          maxlength="64"
          placeholder="插件名：只允许小写字母/数字/下划线"
        >
          <template #prepend>plugins/</template>
          <template #append>.py</template>
        </el-input>

        <div class="code-header">
          <span class="field-label">插件代码</span>
          <div class="code-tools">
            <el-button size="small" @click="fileInput?.click()">
              从文件选择
            </el-button>
            <el-button size="small" @click="fillTemplate">
              填入示例模板
            </el-button>
            <input
              ref="fileInput"
              type="file"
              accept=".py"
              class="file-input"
              @change="onFileChange"
            />
          </div>
        </div>
        <el-input
          v-model="form.code"
          type="textarea"
          class="code-input"
          placeholder="粘贴插件源码，或点击「从文件选择」导入 .py 文件"
        />
        <p v-if="templateHint" class="hint">
          示例匹配包含 hello 的群消息，回复一句问候。
        </p>
        <el-alert
          type="warning"
          show-icon
          :closable="false"
          title="插件会以当前用户权限执行，只安装你信任的代码"
        />
      </div>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">
          安装
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: var(--q-space-4);
}

.btn-icon {
  margin-right: 6px;
}

.plugin-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.plugin-title {
  font-weight: 600;
  color: var(--q-text);
}

.plugin-sub {
  font-size: var(--q-font-12);
  color: var(--q-text-2);
}

.error-text {
  display: block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--q-danger);
}

.desc-text {
  color: var(--q-text-2);
}

.count-text {
  color: var(--q-text-2);
}

.row-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--q-space-2);
}

.install-form {
  display: flex;
  flex-direction: column;
  gap: var(--q-space-3);
}

.code-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--q-space-3);
}

.field-label {
  font-size: var(--q-font-13);
  color: var(--q-text-2);
}

.code-tools {
  display: flex;
  align-items: center;
  gap: var(--q-space-2);
}

.file-input {
  display: none;
}

.code-input :deep(textarea) {
  height: 320px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: var(--q-font-12);
  line-height: 1.6;
}

.hint {
  margin: 0;
  font-size: var(--q-font-12);
  color: var(--q-text-2);
}
</style>
