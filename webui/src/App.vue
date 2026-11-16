<script setup lang="ts">
import { ref } from "vue";
import { clearToken, getToken, setToken } from "./api";
import DashboardView from "./views/DashboardView.vue";
import LogsView from "./views/LogsView.vue";
import PluginsView from "./views/PluginsView.vue";
import SettingsView from "./views/SettingsView.vue";

type ViewName = "dashboard" | "logs" | "plugins" | "settings";

const token = ref(getToken());
const tokenInput = ref("");
const activeTab = ref<ViewName>("dashboard");
const gateError = ref("");

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
}

function editToken(): void {
  gateError.value = "";
  tokenInput.value = "";
  token.value = "";
}

function onUnauthorized(): void {
  clearToken();
  token.value = "";
  gateError.value = "令牌无效或已过期，请重新输入。";
}
</script>

<template>
  <div class="layout">
    <header class="topbar">
      <h1>Qmin 管理面板</h1>
      <el-button v-if="token" text @click="editToken">令牌</el-button>
    </header>

    <section v-if="!token" class="gate">
      <el-card class="gate-card">
        <h2>输入管理令牌</h2>
        <p class="hint">
          令牌位于项目根目录 <code>.env</code> 文件中的
          <code>ADMIN_TOKEN</code>。
        </p>
        <el-input
          v-model="tokenInput"
          type="password"
          placeholder="ADMIN_TOKEN"
          show-password
          @keyup.enter="saveToken"
        />
        <p v-if="gateError" class="gate-error">{{ gateError }}</p>
        <el-button type="primary" class="save-btn" @click="saveToken">
          保存令牌
        </el-button>
      </el-card>
    </section>

    <main v-else class="content">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="仪表盘" name="dashboard">
          <DashboardView
            v-if="activeTab === 'dashboard'"
            @unauthorized="onUnauthorized"
          />
        </el-tab-pane>
        <el-tab-pane label="日志" name="logs">
          <LogsView
            v-if="activeTab === 'logs'"
            @unauthorized="onUnauthorized"
          />
        </el-tab-pane>
        <el-tab-pane label="插件" name="plugins">
          <PluginsView
            v-if="activeTab === 'plugins'"
            @unauthorized="onUnauthorized"
          />
        </el-tab-pane>
        <el-tab-pane label="设置" name="settings">
          <SettingsView
            v-if="activeTab === 'settings'"
            @unauthorized="onUnauthorized"
          />
        </el-tab-pane>
      </el-tabs>
    </main>
  </div>
</template>

<style>
body {
  margin: 0;
  background: #f5f7fa;
  color: #303133;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", Arial, sans-serif;
}

.layout {
  min-height: 100vh;
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
}

.topbar h1 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.gate {
  display: flex;
  justify-content: center;
  padding: 72px 16px;
}

.gate-card {
  width: 100%;
  max-width: 420px;
}

.gate-card h2 {
  margin: 0 0 8px;
  font-size: 16px;
}

.hint {
  margin: 0 0 16px;
  color: #909399;
  font-size: 13px;
}

.gate-error {
  margin: 8px 0 0;
  color: #f56c6c;
  font-size: 13px;
}

.save-btn {
  margin-top: 16px;
  width: 100%;
}

.content {
  padding: 16px 24px 32px;
}

@media (max-width: 600px) {
  .topbar,
  .content {
    padding-left: 16px;
    padding-right: 16px;
  }
}
</style>
