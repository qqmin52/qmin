<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { clearToken, fetchSetupStatus, getToken, setToken } from "./api";
import AppSidebar from "./components/AppSidebar.vue";
import AppTopbar from "./components/AppTopbar.vue";
import DashboardView from "./views/DashboardView.vue";
import LogsView from "./views/LogsView.vue";
import PluginsView from "./views/PluginsView.vue";
import SettingsView from "./views/SettingsView.vue";
import SetupView from "./views/SetupView.vue";

type ViewName = "dashboard" | "logs" | "plugins" | "settings";
type Gate = "loading" | "setup" | "token" | "ready";

const PAGE_META: Record<ViewName, { title: string; subtitle: string }> = {
  dashboard: { title: "仪表盘", subtitle: "机器人运行概览" },
  logs: { title: "运行日志", subtitle: "连接、消息与错误记录" },
  plugins: { title: "插件", subtitle: "启停与加载状态" },
  settings: { title: "设置", subtitle: "凭证、网络与日志配置" },
};

const gate = ref<Gate>("loading");
const token = ref(getToken());
const tokenInput = ref("");
const activeTab = ref<ViewName>("dashboard");
const gateError = ref("");

const pageMeta = computed(() => PAGE_META[activeTab.value]);

async function checkSetup(): Promise<void> {
  try {
    const resp = await fetchSetupStatus();
    if (!resp.configured) {
      gate.value = "setup";
      return;
    }
  } catch {
    // 后端没起或网络错：降级，让老用户直接进令牌输入
  }
  gate.value = "token";
}

function onSetupConfigured(adminToken: string | null) {
  if (adminToken) {
    // SetupView 已替我们 setToken，直接进 ready
    token.value = adminToken;
    gate.value = "ready";
  } else {
    // 令牌已存在或用户点了"进入面板"但没拿到明文
    void checkSetup();
  }
}

function saveToken(): void {
  const value = tokenInput.value.trim();
  if (!value) {
    gateError.value = "请输入管理令牌。";
    return;
  }
  setToken(value);
  token.value = value;
  tokenInput.value = "";
  gateError.value = "";
  gate.value = "ready";
}

function editToken(): void {
  gateError.value = "";
  tokenInput.value = "";
  token.value = "";
  gate.value = "token";
}

function logout(): void {
  clearToken();
  tokenInput.value = "";
  gateError.value = "";
  gate.value = "token";
}

function onUnauthorized(): void {
  clearToken();
  token.value = "";
  gateError.value = "令牌无效或已过期，请重新输入。";
  gate.value = "token";
}

onMounted(() => {
  void checkSetup();
});
</script>

<template>
  <div class="shell">
    <!-- 首次配置向导 -->
    <SetupView v-if="gate === 'setup'" @configured="onSetupConfigured" />

    <!-- loading / 令牌 gate -->
    <div v-else-if="gate !== 'ready'" class="gate">
      <div class="gate-card">
        <div class="brand">
          <span class="mark">Q</span>
          <span class="brand-name">Qmin</span>
        </div>

        <template v-if="gate === 'token'">
          <h2 class="gate-title">输入管理令牌</h2>
          <p class="gate-hint">
            令牌位于项目根目录 <code>.env</code> 文件中的
            <code>ADMIN_TOKEN</code>。
          </p>
          <p class="gate-hint">复制后粘贴到下方输入框，回车即可进入面板。</p>
          <el-input
            v-model="tokenInput"
            type="password"
            placeholder="ADMIN_TOKEN"
            show-password
            @keyup.enter="saveToken"
          />
          <p v-if="gateError" class="gate-error">{{ gateError }}</p>
          <el-button type="primary" class="gate-btn" @click="saveToken">
            保存令牌
          </el-button>
        </template>

        <p v-else class="gate-hint">正在检查配置…</p>
      </div>
    </div>

    <!-- 主界面 -->
    <template v-else>
      <AppSidebar v-model:active="activeTab" />
      <div class="main">
        <AppTopbar
          :title="pageMeta.title"
          :subtitle="pageMeta.subtitle"
          @edit-token="editToken"
          @logout="logout"
          @unauthorized="onUnauthorized"
        />
        <main class="content">
          <DashboardView
            v-if="activeTab === 'dashboard'"
            @unauthorized="onUnauthorized"
            @go-settings="activeTab = 'settings'"
            @go-logs="activeTab = 'logs'"
          />
          <LogsView
            v-else-if="activeTab === 'logs'"
            @unauthorized="onUnauthorized"
          />
          <PluginsView
            v-else-if="activeTab === 'plugins'"
            @unauthorized="onUnauthorized"
          />
          <SettingsView v-else @unauthorized="onUnauthorized" />
        </main>
      </div>
    </template>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  min-height: 100vh;
  background: var(--q-bg);
}

.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.content {
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: var(--q-space-6);
}

/* ---------- gate ---------- */

.gate {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: var(--q-space-6) var(--q-space-4);
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
  font-size: var(--q-font-16);
  font-weight: 600;
  color: var(--q-text);
  margin-bottom: var(--q-space-2);
}

.gate-hint {
  margin-bottom: var(--q-space-2);
  color: var(--q-text-2);
  font-size: var(--q-font-13);
}

.gate-error {
  margin-top: var(--q-space-2);
  color: var(--q-danger);
  font-size: var(--q-font-13);
}

.gate-btn {
  width: 100%;
  margin-top: var(--q-space-4);
}

@media (max-width: 900px) {
  .shell {
    flex-direction: column;
  }

  .content {
    padding: var(--q-space-4);
  }
}
</style>
