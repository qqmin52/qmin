# Qmin（简Q）

![CI](https://github.com/qqmin52/qmin/actions/workflows/ci.yml/badge.svg)

极简 QQ 官方机器人框架：官方 API 零封号、装饰器写插件、自带 Web 面板，半小时跑通。

官网：<https://yf9d.com> · 交流群：[Qmin（简Q）交流群](https://qm.qq.com/q/TdRqj1JjSm)（群号 1058165303）

## 特性

- **官方 API，零封号风险**：只封装 QQ 开放平台官方 Bot API（AppID + AppSecret），不含任何协议逆向。
- **装饰器写插件**：一个函数 + 一个装饰器就是一个插件，面板里安装后立即生效。
- **自带 Web 管理面板**：仪表盘、日志、插件安装与开关、配置修改。**面板是可选件**——不构建也能跑机器人。
- **异常隔离**：单个插件加载失败或运行报错只写日志，不影响其他插件与主进程。
- **依赖少**：Python 3.11+，核心依赖 FastAPI / uvicorn / qq-botpy-sdk / typer / pydantic / aiosqlite。

## 快速开始

环境要求：Python 3.11 及以上；如果需要 Web 面板，再装 Node.js 18+。

### 最短路径：3 分钟跑起机器人（不需要构建前端）

> [!IMPORTANT]
> **不构建前端也能直接跑机器人。** Web 面板只是可选的可视化管理界面：没有构建产物时
> `qmin start` 照常启动机器人、照常收发群消息，只是浏览器打开面板地址会看到一段 JSON 提示。

```bash
git clone https://github.com/qqmin52/qmin.git
cd qmin
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS / Linux: source .venv/bin/activate
pip install -e .
qmin init     # 按提示填 APP_ID / APP_SECRET 等，自动生成管理令牌
qmin doctor   # 检查配置是否完整
qmin start    # 启动：有配置自动连机器人，没配置进入配置向导
```

`qmin doctor` 成功时输出（退出码 0）：

```text
OK  .env 存在：.env
OK  app_id 已填写
OK  app_secret 已填写
OK  admin_token 已设置
OK  插件目录：plugins
OK  插件文件数量：1
```

配置缺失时退出码为 1，并列出缺什么、去哪儿填：

```text
缺少必要的 QQ 机器人配置，请检查项目根目录的 .env 文件：
  1. app_id（.env 变量名 APP_ID）：QQ 开放平台 → 机器人 → 开发设置 → AppID，形如 APP_ID=102345678
  2. app_secret（.env 变量名 APP_SECRET）：同一页面的 AppSecret，形如 APP_SECRET=你的密钥
  3. admin_token（.env 变量名 ADMIN_TOKEN）：管理接口写操作令牌，执行 `qmin init` 可自动生成
提示：先执行 `qmin init` 可按模板生成 .env，并自动生成管理令牌。
```

### 可选：构建 Web 面板

> [!TIP]
> **Windows 用户注意**：npm 命令请写成 `npm.cmd`（如 `npm.cmd install`、`npm.cmd run build`）。
> 直接写 `npm` 在 PowerShell 里可能因执行策略拒绝运行 `npm.ps1`。

```bash
cd webui
npm install
npm run build
cd ..
```

构建产物输出到 `api/static/`，由 `qmin start` 在同一个地址托管。重新 `qmin start` 后打开
<http://127.0.0.1:8000>，用 `qmin token` 复制的令牌登录即可。

> 配置不完整、面板又还没构建时，浏览器只会看到 JSON 提示；这时用 `qmin init` 补配置即可。

## 写第一个插件

最小可用插件（仓库里也有一份模板：`plugins/_template.py`，下划线开头的文件不会被当成插件加载）：

```python
"""示例插件：收到包含“你好”的群 @ 消息时回复。"""

from core.handlers import on_group_at

__plugin_name__ = "打招呼"
__description__ = "收到包含“你好”的群消息时回复"
__version__ = "1.0.0"


@on_group_at("你好")
async def hello(event) -> None:
    await event.reply("你好呀")
```

三种安装方式：

| 方式 | 是否立即生效 |
| --- | --- |
| 面板「插件 → 安装插件」粘贴代码或选择 `.py` 文件 | 是，安装即加载 |
| 面板「插件」页对已存在的插件点「重新加载」 | 是，改完文件点一下即可 |
| 直接往 `plugins/` 目录放 `.py` 文件 | 否，需要重启 `qmin start` |

### 当前支持范围

- **支持**：群聊里 @ 机器人的文本消息（`on_group_at`），处理器里可以回复文本。
- **暂未封装**：按钮 / 卡片等交互组件（keyboard、ark）、私聊消息、频道消息、主动推送。
  这些目前需要自行调用 qq-botpy SDK，框架层没有对应装饰器；有需要欢迎开 issue 说明场景。

完整参考见 [docs/PLUGINS.md](docs/PLUGINS.md)。

## 管理面板

- `qmin start` 启动面板；配置完整时自动连接机器人，配置缺失时进入配置向导。
- 首次使用需要输入管理令牌：`qmin token` 复制到剪贴板，或查看 `.env` 的 `ADMIN_TOKEN`。
- 四个页面：仪表盘（连接状态、运行时长、插件数、日志数）、日志（SQLite 落库、筛选、加载更早）、
  插件（安装 / 启用 / 重新加载 / 删除）、设置（凭证与网络配置；凭证改完点启动即生效）。

## 命令一览

| 命令 | 说明 |
| --- | --- |
| `qmin init` | 交互式生成 `.env`，并自动创建管理令牌。 |
| `qmin doctor` | 只读检查配置与插件目录，不写文件、不发网络请求。 |
| `qmin start` | 一条命令启动：有配置自动连机器人，没配置进入配置向导。 |
| `qmin token` | 复制管理令牌到剪贴板；加 `--show` 直接打印明文。 |

> 旧版 `qmin run` / `qmin api` 已合并为 `qmin start`。

## 配置项

| 键 | 含义 | 默认值 |
| --- | --- | --- |
| `APP_ID` | QQ 开放平台机器人 AppID | 无（必填） |
| `APP_SECRET` | QQ 开放平台机器人 AppSecret | 无（必填） |
| `ADMIN_TOKEN` | 管理面板与写接口令牌 | 自动生成随机值 |
| `HOST` | 管理接口监听地址 | `127.0.0.1` |
| `PORT` | 管理接口监听端口 | `8000` |
| `LOG_LEVEL` | 日志级别：DEBUG / INFO / WARNING / ERROR | `INFO` |
| `DB_PATH` | SQLite 数据库文件路径（日志持久化） | `qmin.db` |
| `LOG_MAX_ROWS` | 日志表最多保留行数，超出裁剪最旧记录 | `50000` |
| `LOG_SDK` | SDK 日志导流：`off` 只导 WARNING+，`all` 连 INFO 一起导 | `off` |
| `LOG_MESSAGE_CONTENT` | 入站消息日志是否记录正文 | `true` |

## 文档

- [插件开发指南](docs/PLUGINS.md)：装饰器、event 字段、生命周期与热重载边界
- [架构说明](docs/ARCHITECTURE.md)：数据流与各模块职责
- [贡献指南](CONTRIBUTING.md)：改哪儿、怎么验证
- [v0.1.0 发布说明](docs/RELEASE_v0.1.0.md)：能力、限制、下一步

## 常见问题

**收不到群消息？**
群里必须 @ 机器人，普通聊天不会触发；机器人也需要在开放平台「沙箱配置」里加入测试群。
被动回复需在收到消息后 5 分钟内完成。

**管理面板打不开 / 打开是一段 JSON？**
先确认前端构建产物是否存在：执行过 `npm run build` 才会有面板。
`qmin start` 启动时如果检测不到 `api/static/index.html`，会打印提示，`/` 返回 `panel_not_built` JSON。

**管理面板要令牌，忘了？**
执行 `qmin token` 复制到剪贴板，或打开 `.env` 看 `ADMIN_TOKEN`。

**插件没生效？**
面板安装/重新加载是立即生效的；直接放进 `plugins/` 的文件要重启。
仍不生效时执行 `qmin doctor` 看插件数量，再到面板「日志」页看加载错误。

## 安全与合规

Qmin 只封装 QQ 开放平台官方 Bot API，不包含任何协议逆向代码；项目名带 Q 字样，但不代表腾讯官方产品。
请勿把 `.env`（含 AppSecret 与管理令牌）提交到仓库——它已在 `.gitignore` 中。

## 开发

```powershell
.venv\Scripts\python.exe -m pytest        # 后端测试
cd webui; npm.cmd run build; cd ..        # 修改前端后重新构建（需要 Node 18+）
```

构建产物输出到 `api/static/`，由管理 API 直接托管，无需单独部署。改设计或加功能前请先看
[CONTRIBUTING.md](CONTRIBUTING.md)。
