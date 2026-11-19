# 贡献指南

欢迎提交 issue 和 PR。改动较大（新增事件类型、改数据库结构、动面板交互）时，建议先开 issue 说明场景，
避免写完才发现方向不一致。

## 开发环境

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"      # 带 pytest / pytest-asyncio / httpx
.venv\Scripts\python.exe -m pytest
```

改前端需要 Node.js 18+：

```powershell
cd webui
npm.cmd install
npm.cmd run build            # 产物输出到 api/static/
```

## 提交前必须检查

1. **测试全绿**：`.venv\Scripts\python.exe -m pytest -q`，当前基线是 144 passed。
2. **改过前端就重新构建**：`npm.cmd run build`，并实际打开面板点一遍受影响的页面（`api/static/` 不入库，
   别人 clone 下来会自己构建）。
3. **不要提交本地文件**：`.env`、`qmin.db`、`node_modules/`、`api/static/`、日志文件都已在 `.gitignore` 里，
   `git status` 提交前看一眼。
4. **没有自动化测试覆盖的改动，必须在 PR 里写手动验证步骤和实际输出**——这是硬性要求，见下文。
5. **发版前**：先 `npm.cmd run build`（生成面板产物），再 `python -m build`，并确认 wheel 里
   包含 `api/static/index.html`（`unzip -l dist/qmin-*.whl` 可查）。

## CI

每个 PR 都会跑 GitHub Actions：pytest（Linux / Windows × Python 3.11 / 3.13）、
前端构建、敏感文件检查。三个 job 全绿才合并。
本地先跑 `.venv\Scripts\python.exe -m pytest -q`；改过前端再跑 `npm.cmd run build`。

## 改哪儿的速查表

| 你想做的事 | 必须改的文件 | 还要补 |
| --- | --- | --- |
| 新增事件装饰器（如私聊、频道消息） | `core/events.py`（事件模型）→ `core/handlers.py`（装饰器 + 分发）→ `core/bot.py`（接 SDK 回调） | 测试：注册、命中、异常隔离、重载不翻倍；`docs/PLUGINS.md` 的装饰器表；README「当前支持范围」 |
| 新增管理接口 | `api/routes/xxx.py` → `api/schema.py`（请求/响应模型）→ `api/main.py` 挂载 | 测试：鉴权（401）、非法入参、正常路径；README 面板说明 |
| 新增 CLI 命令 | `core/cli.py` | 测试：`tests/test_cli.py` 用 `CliRunner` 断言输出与退出码；README 命令表 |
| 修改插件加载 / 热重载 | `core/plugins.py` | 测试：`tests/test_plugins.py`（安装、覆盖、重载后处理器数为 1、失败回滚）；`docs/PLUGINS.md` 生命周期一节 |
| 修改日志 / 持久化 | `core/logstore.py`、`core/state.py` | 测试：`tests/test_logstore.py`（落库、分页、保留策略、关闭写干净）；注意失败必须降级到内存 |
| 修改面板 | `webui/src/` | `npm.cmd run build` + 手动点四个页面（仪表盘/日志/插件/设置），附截图 |
| 修改配置项 | `core/config.py` + `.env.example` | 测试：`tests/test_config.py`（解析、校验、默认值）；README 配置表 |

## 验证要求

**必须有自动化测试的改动**（缺了会被要求补）：

- 新的装饰器：注册后能被 `Router` 命中、`keyword=None` 匹配全部、异常被隔离且不影响后续处理器。
- 插件生命周期：安装 / 重新加载 / 覆盖后 `handler_count == 1`（不能翻倍）、加载失败回滚文件。
- 管理接口：无令牌 401、非法参数 4xx、正常路径 2xx。
- 配置解析：缺项报错、非法值报错、默认值正确。

**只能用手动验证的部分**（写清步骤和结果）：

- 面板交互（安装对话框、日志筛选、加载更早、启停按钮）
- 真实的 QQ 收发（需要真实 AppID 与测试群）
- 启动/退出流程（Ctrl+C 后日志是否落库）

手动验证请按这个格式写进 PR：

```text
1. 执行 qmin start
2. 打开面板 → 插件 → 安装插件 → 填入示例模板 → 安装
3. 群里 @机器人 hello
期望：面板插件列表出现 hello_demo，状态「启用·已加载」；群里收到回复
实际：<贴关键日志行或截图>
```

## 代码约定

- Python 3.11+，公开函数写类型注解，注释用中文。
- **分层不能破**：`core/` 不 import `api/`、不依赖 FastAPI；`api/` 不直接操作 botpy。
- 日志统一用 `await state.add_log(level, source, message)`，不要用 `print`（CLI 命令的人机提示除外）。
- 异步代码里不要调用阻塞库（`requests`、`time.sleep`、同步文件大 IO）。
- 新增依赖需要说明理由；能只用标准库就不要加。
- 插件是任意代码执行入口：涉及安装/删除接口时，必须保留令牌 + Origin 校验与文件名白名单。

## 提交信息

用 `类型(范围): 说明` 的格式，类型用 `feat` / `fix` / `docs` / `chore`，范围可选（`core`、`cli`、`webui`、`docs`）：

```text
feat(core): 支持私聊消息装饰器 on_c2c
fix(plugins): 覆盖安装失败时回滚到上一版本
docs: 补充插件热重载边界说明
```

## Pull Request

- 一个 PR 只做一件事，避免混入无关格式化。
- 描述里写清：改了什么、为什么、怎么验证（自动化命令 + 手动步骤）。
- 改前端请附截图；改行为请说明对现有用户的影响（是否破坏兼容）。
- 提交前确认 `git status` 里没有 `.env`、数据库或构建产物。

## 行为准则

保持技术讨论对事不对人；不接受任何绕过 QQ 平台规则、协议逆向或账号登录相关的贡献。
