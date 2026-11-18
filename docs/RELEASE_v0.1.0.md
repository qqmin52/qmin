# Qmin v0.1.0 发布说明

发布日期：2026-11-17

第一个可用版本。目标很明确：**让没写过 QQ 机器人的人，半小时内跑通一个能回话的机器人**。

## 核心能力

- **官方 API，零封号风险**：只使用 QQ 开放平台官方 Bot API（AppID + AppSecret），不含协议逆向。
- **一条命令启动**：`qmin start` 有配置就自动连机器人，没配置就进配置向导。
- **装饰器写插件**：`@on_group_at("关键字")` + 一个异步函数就是插件；面板里安装即生效，改完点「重新加载」即可热更新。
- **Web 管理面板**（可选）：仪表盘、日志、插件安装/启用/删除、配置修改；面板里改凭证，点启动即用新凭证，不用重启。
- **日志可追溯**：SQLite 落库，重启不丢；支持按级别/来源/关键词筛选与「加载更早」。
- **异常隔离**：单个插件加载失败或运行报错只写日志，不影响其他插件与机器人本体。

## 快速开始

```bash
git clone https://github.com/qqmin52/qmin.git
cd qmin
python -m venv .venv && .venv\Scripts\activate     # macOS/Linux: source .venv/bin/activate
pip install -e .
qmin init
qmin start
```

不构建前端也能直接跑机器人；想要面板再执行一次：

```bash
cd webui && npm install && npm run build && cd ..
```

## 已知限制

| 限制 | 说明 |
| --- | --- |
| 只支持群 @ 文本消息 | 按钮 / 卡片（keyboard、ark）、私聊、频道消息、主动推送暂未封装装饰器 |
| 插件之间不能互相调用 | 每个插件是独立文件，`plugins/` 不在 `sys.path` |
| 手动放插件文件需要重启 | 面板安装 / 重新加载可以热生效，直接放文件不会自动加载 |
| 沙箱环境未暴露配置 | 未上线的机器人需要沙箱环境，当前版本固定连正式环境 |
| 一个进程一个机器人 | 单个 `qmin start` 只管理一个 AppID 的连接 |
| 日志默认保留 5 万行 | 超出后自动裁剪最旧记录，可用 `LOG_MAX_ROWS` 调整 |
| 面板需自行构建 | 仓库不包含 `api/static/` 产物，未构建时访问面板只会看到 JSON 提示 |

## 下一步

- `sandbox` 配置项：支持未上线机器人的沙箱调试。
- 更多事件装饰器：私聊消息、频道消息、按钮/卡片交互回调。
- 面板：暗色模式、移动端细节优化。
- 插件生态：更完整的示例插件与模板列表。

## 兼容性说明

- 旧版 `qmin run` / `qmin api` 已合并为 `qmin start`，旧命令会报 `No such command`。
- 配置项完全向后兼容：新增的 `LOG_MAX_ROWS`、`LOG_SDK`、`LOG_MESSAGE_CONTENT` 都有默认值。
