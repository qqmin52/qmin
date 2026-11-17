<script setup lang="ts">
import { ref } from "vue";
import { ElMessage } from "element-plus";
import { clearToken, completeSetup, setToken } from "../api";

type Step = "form" | "done";

const emit = defineEmits<{
  configured: [adminToken: string | null];
}>();

const step = ref<Step>("form");
const appId = ref("");
const appSecret = ref("");
const submitting = ref(false);
const error = ref("");
const adminTokenPlain = ref<string | null>(null);
const tokenAlreadyExisted = ref(false);
const copied = ref(false);

async function submit(): Promise<void> {
  const id = appId.value.trim();
  const secret = appSecret.value.trim();
  if (!id || !secret) {
    error.value = "请填写完整的 AppID 和 AppSecret。";
    return;
  }
  submitting.value = true;
  error.value = "";
  try {
    const resp = await completeSetup({ app_id: id, app_secret: secret });
    adminTokenPlain.value = resp.admin_token;
    tokenAlreadyExisted.value = resp.token_already_existed;
    step.value = "done";
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (msg === "already_configured") {
      ElMessage.error("已配置，无需重复提交。");
      return;
    }
    if (msg.startsWith("HTTP 422")) {
      error.value = "请填写完整的 AppID 和 AppSecret。";
      return;
    }
    error.value = msg;
  } finally {
    submitting.value = false;
  }
}

async function copyToken(): Promise<void> {
  if (!adminTokenPlain.value) return;
  try {
    await navigator.clipboard.writeText(adminTokenPlain.value);
    copied.value = true;
    ElMessage.success("已复制");
  } catch {
    ElMessage.warning("复制失败，请手动复制。");
  }
}

function enterPanelWithToken(): void {
  if (adminTokenPlain.value) {
    // 首次生成的令牌：直接写入 localStorage，跳过 TokenGate
    clearToken();
    setToken(adminTokenPlain.value);
    emit("configured", adminTokenPlain.value);
  }
}

function enterPanelNoToken(): void {
  emit("configured", null);
}
</script>

<template>
  <div class="gate">
    <div class="gate-card">
      <div class="brand">
        <span class="mark">Q</span>
        <span class="brand-name">Qmin</span>
      </div>

      <template v-if="step === 'form'">
        <h2 class="gate-title">首次配置</h2>
        <p class="hint">
          请填写 QQ 开放平台的 AppID 与 AppSecret。填写完成后，管理令牌会自动生成。
        </p>
        <el-input
          v-model="appId"
          placeholder="AppID（形如 100000001）"
          @keyup.enter="submit"
        />
        <el-input
          v-model="appSecret"
          type="password"
          show-password
          placeholder="AppSecret"
          class="secret-input"
          @keyup.enter="submit"
        />
        <p v-if="error" class="gate-error">{{ error }}</p>
        <el-button
          type="primary"
          class="save-btn"
          :loading="submitting"
          @click="submit"
        >
          保存并连接
        </el-button>
      </template>

      <template v-else-if="adminTokenPlain">
        <h2 class="gate-title">配置已保存</h2>
        <p class="hint">
          请复制下方管理令牌并保存到安全位置。令牌只在本次返回一次明文。
        </p>
        <div class="token-box">
          <el-input :model-value="adminTokenPlain" readonly />
          <el-button :disabled="copied" @click="copyToken">
            {{ copied ? "已复制" : "复制令牌" }}
          </el-button>
        </div>
        <el-button
          type="primary"
          class="save-btn"
          @click="enterPanelWithToken"
        >
          已保存令牌，进入面板
        </el-button>
      </template>

      <template v-else-if="tokenAlreadyExisted">
        <h2 class="gate-title">配置已保存</h2>
        <p class="hint">
          管理令牌已存在于 <code>.env</code>，请打开该文件复制
          <code>ADMIN_TOKEN</code>，然后重新打开本页面。
        </p>
        <el-button type="primary" class="save-btn" @click="enterPanelNoToken">
          我已保存令牌，进入面板
        </el-button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.gate {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: var(--q-space-6) var(--q-space-4);
  background: var(--q-bg);
}

.gate-card {
  width: 100%;
  max-width: 420px;
  padding: 32px;
  background: var(--q-surface);
  border: 1px solid var(--q-border);
  border-radius: var(--q-radius-lg);
  box-shadow: var(--q-shadow);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--q-space-3);
  margin-bottom: var(--q-space-5);
}

.mark {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--q-radius-sm);
  background: var(--q-primary);
  color: var(--q-surface);
  font-size: var(--q-font-16);
  font-weight: 600;
}

.brand-name {
  font-size: var(--q-font-20);
  font-weight: 600;
  color: var(--q-text);
}

.gate-title {
  margin-bottom: var(--q-space-2);
  font-size: var(--q-font-16);
  font-weight: 600;
  color: var(--q-text);
}

.hint {
  margin-bottom: var(--q-space-4);
  color: var(--q-text-2);
  font-size: var(--q-font-13);
}

.secret-input {
  margin-top: var(--q-space-3);
}

.token-box {
  display: flex;
  gap: var(--q-space-2);
  align-items: center;
}

.gate-error {
  margin-top: var(--q-space-2);
  color: var(--q-danger);
  font-size: var(--q-font-13);
}

.save-btn {
  margin-top: var(--q-space-4);
  width: 100%;
}
</style>
