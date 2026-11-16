# Qmin（简Q）

Qmin（简Q）：极简 QQ 官方机器人框架，新手半小时跑通第一个机器人。

## 特性

- **官方 API，零封号风险**：完全基于 QQ 开放平台官方 Bot API（AppID + AppSecret），不涉及协议逆向。
- **装饰器写插件**：一个函数 + 一个装饰器就是插件，丢进 `plugins/` 即生效。
- **自带 Web 管理面板**：仪表盘、日志、插件开关、配置修改，开箱即用。
- **异常隔离**：单个插件加载失败或运行报错只记录日志，不影响其他插件与主进程。
- **依赖少**：纯 Python 实现，核心依赖仅 FastAPI、uvicorn、qq-botpy、typer、pydantic。

## 快速开始（5 分钟）

环境要求：Python 3.11 及以上。

```bash
git clone <你的仓库地址> qmin
cd qmin
python -m venv .venv
```

激活虚拟环境（Windows）：

```powershell
.venv\Scripts\activate
```

激活虚拟环境（macOS / Linux）：

```bash
source .venv/bin/activate
```

安装并启动：

```bash
pip install -e .
qmin init
qmin doctor
qmin run
```

`qmin init` 会依次询问 APP_ID、APP_SECRET、HOST、PORT、LOG_LEVEL、DB_PATH，并自动生成管理令牌写入 `.env`。
`qmin doctor` 用于检查配置是否完整，`qmin run` 同时启动机器人与管理面板。

## 写第一个插件

在 `plugins/hello.py` 新建文件，内容如下（与仓库自带示例一致）：

```python
"""示例插件：收到包含“你好”的群 @ 消息时回复。"""

from core.handlers import on_group_at


@on_group_at("你好")
async def hello(event) -> None:
    """回复固定文案。"""
    await event.reply("你好呀")
```

丢进 `plugins/` 目录即生效，在管理面板的「插件」页可随时禁用或重新启用。

## 管理面板

- `qmin run`：同时启动机器人与管理面板，默认地址 <http://127.0.0.1:8000>。
- `qmin api`：只启动管理面板，不连接 QQ，不会占用机器人登录。
- 首次使用需要输入管理令牌，令牌位于 `.env` 文件的 `ADMIN_TOKEN`。
- 面板包含四个页面：仪表盘（连接状态、运行时长、插件数、日志数）、日志（增量轮询 + 暂停滚动）、插件（启用/禁用开关与加载错误）、设置（修改配置并写入 `.env`）。

## 命令一览

| 命令 | 说明 |
| --- | --- |
| `qmin init` | 交互式生成 `.env`，并自动创建管理令牌。 |
| `qmin doctor` | 只读检查配置与插件目录，不写文件、不发网络请求。 |
| `qmin run` | 加载插件，同时启动机器人与管理 API。 |
| `qmin api` | 只启动管理面板，不连接 QQ（不会占用机器人登录）。 |

## 配置项

| 键 | 含义 | 默认值 |
| --- | --- | --- |
| `APP_ID` | QQ 开放平台机器人 AppID | 无（必填） |
| `APP_SECRET` | QQ 开放平台机器人 AppSecret | 无（必填） |
| `ADMIN_TOKEN` | 管理面板与写接口令牌 | 自动生成随机值 |
| `HOST` | 管理接口监听地址 | `127.0.0.1` |
| `PORT` | 管理接口监听端口 | `8000` |
| `LOG_LEVEL` | 日志级别：DEBUG / INFO / WARNING / ERROR | `INFO` |
| `DB_PATH` | SQLite 数据库文件路径 | `qmin.db` |

## 常见问题

**收不到群消息？**
群里必须 @ 机器人，普通聊天不会触发。被动回复需在收到消息后 5 分钟内完成。

**管理面板打不开？**
确认 `qmin` 或 `qmin api` 正在运行，并访问终端打印的地址。令牌错误时页面会退回令牌输入界面。

**插件没生效？**
执行 `qmin doctor` 查看插件文件数量，再到面板「日志」页查看加载错误信息。

## 安全与合规

Qmin 仅封装 QQ 开放平台官方 Bot API，不包含任何协议逆向代码；项目带 Q 字样，但不代表腾讯官方产品。

## 开发

运行后端测试：

```powershell
.venv\Scripts\python.exe -m pytest
```

修改前端后重新构建（需要 Node 18+）：

```bash
cd webui && npm.cmd run build
```

构建产物输出到 `api/static/`，由管理 API 直接托管，无需单独部署。
