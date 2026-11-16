<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { UnauthorizedError, fetchConfig, updateConfig } from "../api";
import type { ConfigOut, ConfigUpdateRequest } from "../types";

const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"];

const emit = defineEmits<{ unauthorized: [] }>();

const config = ref<ConfigOut | null>(null);
const loading = ref(false);
const saving = ref(false);
const error = ref("");

const form = reactive({
  app_secret: "",
  host: "",
  port: 8000,
  log_level: "INFO",
});

const initial = reactive({
  host: "",
  port: 8000,
  log_level: "INFO",
});

function applyConfig(data: ConfigOut): void {
  config.value = data;
  form.app_secret = "";
  form.host = data.host;
  form.port = data.port;
  form.log_level = data.log_level;
  initial.host = data.host;
  initial.port = data.port;
  initial.log_level = data.log_level;
}

async function load(): Promise<void> {
  loading.value = true;
  try {
    applyConfig(await fetchConfig());
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

function buildPayload(): ConfigUpdateRequest {
  const payload: ConfigUpdateRequest = {};
  const secret = form.app_secret.trim();
  if (secret) {
    payload.app_secret = secret;
  }
  if (form.host !== initial.host) {
    payload.host = form.host;
  }
  if (form.port !== initial.port) {
    payload.port = form.port;
  }
  if (form.log_level !== initial.log_level) {
    payload.log_level = form.log_level;
  }
  return payload;
}

async function save(): Promise<void> {
  const payload = buildPayload();
  if (Object.keys(payload).length === 0) {
    ElMessage.info("没有修改");
    return;
  }

  try {
    await ElMessageBox.confirm(
      "修改将写入 .env，需要重启 qmin 后才生效，确定保存？",
      "确认保存",
      {
        confirmButtonText: "确定保存",
        cancelButtonText: "取消",
        type: "warning",
      },
    );
  } catch {
    return;
  }

  saving.value = true;
  try {
    await updateConfig(payload);
    ElMessage.success("已保存，请重启 qmin 生效");
    await load();
  } catch (err) {
    if (err instanceof UnauthorizedError) {
      emit("unauthorized");
      return;
    }
    if (err instanceof Error && err.message === "HTTP 422") {
      ElMessage.error("字段格式不正确");
      return;
    }
    ElMessage.error(err instanceof Error ? err.message : String(err));
  } finally {
    saving.value = false;
  }
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div v-loading="loading">
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
      class="alert"
    />

    <el-form label-width="110px" class="form">
      <el-form-item label="APP_ID">
        <el-input :model-value="config?.app_id ?? ''" disabled />
      </el-form-item>

      <el-form-item label="APP_SECRET">
        <el-input
          v-model="form.app_secret"
          type="password"
          show-password
          :placeholder="config?.app_secret ?? '留空表示不修改'"
        />
        <p class="hint">留空表示不修改</p>
      </el-form-item>

      <el-form-item label="HOST">
        <el-input v-model="form.host" />
      </el-form-item>

      <el-form-item label="PORT">
        <el-input-number v-model="form.port" :min="1" :max="65535" />
      </el-form-item>

      <el-form-item label="LOG_LEVEL">
        <el-select v-model="form.log_level" class="select">
          <el-option
            v-for="level in LOG_LEVELS"
            :key="level"
            :label="level"
            :value="level"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="DB_PATH">
        <el-input :model-value="config?.db_path ?? ''" disabled />
      </el-form-item>

      <el-form-item>
        <el-button type="primary" :loading="saving" @click="save">
          保存
        </el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<style scoped>
.alert {
  margin-bottom: 16px;
}

.form {
  max-width: 560px;
}

.hint {
  margin: 4px 0 0;
  color: #909399;
  font-size: 12px;
}

.select {
  width: 100%;
}
</style>
