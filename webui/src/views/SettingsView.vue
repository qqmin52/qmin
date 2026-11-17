<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { UnauthorizedError, fetchConfig, updateConfig } from "../api";
import type { ConfigOut, ConfigUpdateRequest } from "../types";
import SectionCard from "../components/SectionCard.vue";

const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"];

const emit = defineEmits<{ unauthorized: [] }>();

const config = ref<ConfigOut | null>(null);
const loading = ref(false);
const saving = ref(false);
const error = ref("");

const form = reactive({
  app_id: "",
  app_secret: "",
  host: "",
  port: 8000,
  log_level: "INFO",
});

const initial = reactive({
  app_id: "",
  host: "",
  port: 8000,
  log_level: "INFO",
});

function applyConfig(data: ConfigOut): void {
  config.value = data;
  form.app_secret = "";
  form.app_id = data.app_id;
  form.host = data.host;
  form.port = data.port;
  form.log_level = data.log_level;
  initial.app_id = data.app_id;
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
  const id = form.app_id.trim();
  if (id !== "" && id !== initial.app_id) {
    payload.app_id = id;
  }
  const secret = form.app_secret.trim();
  if (secret !== "") {
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
      "修改将写入 .env；应用 / 端口变更需重启 qmin api，凭证变更下次启动机器人即生效。确定保存？",
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

    // 根据 payload 字段给分类提示：
    //   凭证类（app_id / app_secret）→ BotManager 每次 start 都从 .env 读，不重启进程也生效
    //   监听类（host/port）→ uvicorn 监听地址不热更，必须重启 qmin api
    const keys = Object.keys(payload);
    const hasCredentialChange = keys.includes("app_id") || keys.includes("app_secret");
    const hasListenerChange = keys.includes("host") || keys.includes("port");

    const msgs: string[] = [];
    if (hasCredentialChange) {
      msgs.push("已保存，点『启动机器人』即用新凭证");
    }
    if (hasListenerChange) {
      msgs.push("已保存，监听地址变更需重启 qmin api");
    }
    if (msgs.length === 0) {
      msgs.push("已保存");
    }
    ElMessage.success(msgs.join("；"));
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
  <div v-loading="loading" class="page">
    <el-alert
      v-if="error"
      :title="error"
      type="error"
      show-icon
      :closable="false"
    />

    <SectionCard title="凭证" description="QQ 开放平台的机器人身份">
      <el-form label-position="top" class="form">
        <el-form-item label="APP_ID">
          <el-input v-model="form.app_id" placeholder="QQ 开放平台 AppID" />
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
      </el-form>
      <div class="footer">
        <span class="footer-hint">保存后点『启动机器人』即用新凭证</span>
        <el-button type="primary" :loading="saving" @click="save">
          保存
        </el-button>
      </div>
    </SectionCard>

    <SectionCard title="网络" description="管理面板的监听地址">
      <el-form label-position="top" class="form">
        <el-form-item label="HOST">
          <el-input v-model="form.host" />
        </el-form-item>
        <el-form-item label="PORT">
          <el-input-number v-model="form.port" :min="1" :max="65535" />
        </el-form-item>
      </el-form>
      <div class="footer">
        <span class="footer-hint">修改监听地址需重启 qmin api</span>
        <el-button type="primary" :loading="saving" @click="save">
          保存
        </el-button>
      </div>
    </SectionCard>

    <SectionCard title="其它" description="日志与数据文件">
      <el-form label-position="top" class="form">
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
          <p class="hint">日志数据库文件，暂不支持在面板中修改</p>
        </el-form-item>
      </el-form>
      <div class="footer">
        <el-button type="primary" :loading="saving" @click="save">
          保存
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

.form {
  max-width: 520px;
}

.hint {
  margin: var(--q-space-1) 0 0;
  color: var(--q-text-3);
  font-size: var(--q-font-12);
}

.select {
  width: 100%;
}

.footer {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--q-space-3);
  margin-top: var(--q-space-2);
  padding-top: var(--q-space-4);
  border-top: 1px solid var(--q-border);
}

.footer-hint {
  color: var(--q-text-2);
  font-size: var(--q-font-12);
}
</style>
