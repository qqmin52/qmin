"""管理接口的请求 / 响应模型（骨架）。

本模块是 ``/api/*`` 的唯一对外契约来源：路由层只使用这里的模型，
前端类型定义也以此为准。约定：

- 全部 pydantic v2 模型。
- 请求体默认 ``extra="forbid"``，拒绝未知字段，避免前端拼错字段静默生效。
- 响应中绝不包含 AppSecret 明文或完整 admin token。
- 时间统一为 ISO 8601 字符串（含时区）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


# ---------------------------------------------------------------- 通用


class ErrorResponse(BaseModel):
    """统一错误响应体。

    Attributes:
        code: 机器可读的错误码，如 ``unauthorized`` / ``invalid_config``。
        detail: 面向人类的中文错误说明。
    """

    code: str = Field(description="机器可读错误码")
    detail: str = Field(description="中文错误说明")


class HealthResponse(BaseModel):
    """``GET /api/health`` 响应（无需鉴权，仅用于探活）。

    Attributes:
        status: 固定为 ``ok``。
    """

    status: str = Field(description="服务状态")


# ---------------------------------------------------------------- 状态


class StatusResponse(BaseModel):
    """``GET /api/status`` 响应。

    Attributes:
        connected: WebSocket 是否已连接。
        started_at: 进程启动时间，未启动为 ``None``。
        uptime_seconds: 已运行秒数。
        plugin_total: 发现的插件总数。
        plugin_enabled: 已启用插件数。
        plugin_loaded: 已成功加载插件数。
        log_count: 当前环形缓冲中的日志条数。
    """

    connected: bool = Field(description="WebSocket 是否已连接")
    started_at: datetime | None = Field(default=None, description="启动时间")
    uptime_seconds: float = Field(ge=0, description="已运行秒数")
    plugin_total: int = Field(ge=0, description="插件总数")
    plugin_enabled: int = Field(ge=0, description="已启用插件数")
    plugin_loaded: int = Field(ge=0, description="已成功加载插件数")
    log_count: int = Field(ge=0, description="日志条数")


# ---------------------------------------------------------------- 插件


class PluginInfo(BaseModel):
    """单个插件的展示信息。

    Attributes:
        name: 插件名（文件名去扩展名）。
        enabled: 是否启用。
        loaded: 是否已成功加载。
        handler_count: 注册的处理器数量。
        error: 加载失败摘要，成功为 ``None``。
        display_name: 插件自报的显示名（``__plugin_name__``）。
        description: 插件自报的描述（``__description__``）。
        version: 插件自报的版本（``__version__``）。
    """

    name: str = Field(description="插件名")
    enabled: bool = Field(description="是否启用")
    loaded: bool = Field(description="是否已加载")
    handler_count: int = Field(default=0, ge=0, description="处理器数量")
    error: str | None = Field(default=None, description="加载失败摘要")
    display_name: str | None = Field(default=None, description="插件显示名")
    description: str | None = Field(default=None, description="插件描述")
    version: str | None = Field(default=None, description="插件版本")


class PluginListResponse(BaseModel):
    """``GET /api/plugins`` 响应。

    Attributes:
        items: 插件列表。
        total: 插件总数。
    """

    items: list[PluginInfo] = Field(description="插件列表")
    total: int = Field(ge=0, description="插件总数")


class TogglePluginRequest(BaseModel):
    """``POST /api/plugins/{name}/toggle`` 请求体。

    Attributes:
        enabled: 目标启用状态。
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(description="目标启用状态")


class InstallPluginRequest(BaseModel):
    """``POST /api/plugins/install`` 请求体。

    Attributes:
        name: 插件名（同时也是 ``plugins/<name>.py`` 的文件名）。
        code: 插件源码全文。
        overwrite: 同名插件已存在时是否覆盖。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="插件名")
    code: str = Field(description="插件源码")
    overwrite: bool = Field(default=False, description="同名时是否覆盖")


class RemovePluginResponse(BaseModel):
    """``DELETE /api/plugins/{name}`` 响应。"""

    removed: bool = Field(description="是否已移除")


# ---------------------------------------------------------------- 日志


class LogItem(BaseModel):
    """单条日志。

    Attributes:
        seq: 单调递增序号。
        time: 产生时间。
        level: 日志级别。
        source: 来源标识（插件名或模块名）。
        message: 日志正文。
    """

    seq: int = Field(ge=0, description="递增序号")
    time: datetime = Field(description="产生时间")
    level: LogLevel = Field(description="日志级别")
    source: str = Field(description="来源标识")
    message: str = Field(description="日志正文")


class LogsResponse(BaseModel):
    """``GET /api/logs`` 响应。

    Attributes:
        items: 按时间正序排列的日志。
        total: 本次返回条数。
        latest_seq: **服务端真实最新序号**（不是 after_seq 回声）。
            这是服务重启回补的唯一可靠信号——重启后环形缓冲清空、序号从 0 重新计数，
            因而此值会比前端上一次记录的 latestSeq 小。
        buffer_total: 当前环形缓冲内的总条数。
    """

    items: list[LogItem] = Field(description="日志列表")
    total: int = Field(ge=0, description="本次返回条数")
    latest_seq: int = Field(ge=0, description="服务端真实最新日志序号")
    buffer_total: int = Field(ge=0, description="环形缓冲内当前总条数")


# ---------------------------------------------------------------- 配置


class ConfigOut(BaseModel):
    """``GET /api/config`` 响应（脱敏）。

    Attributes:
        app_id: QQ 开放平台 AppID。
        app_secret: 恒为打码字符串，绝不回传明文。
        host: 管理接口监听地址。
        port: 管理接口监听端口。
        log_level: 日志级别。
        db_path: SQLite 文件路径。
        admin_token_set: 是否已设置管理令牌（不回传令牌本身）。
    """

    app_id: str = Field(description="AppID")
    app_secret: str = Field(description="打码后的 AppSecret")
    host: str = Field(description="监听地址")
    port: int = Field(ge=1, le=65535, description="监听端口")
    log_level: str = Field(description="日志级别")
    db_path: str = Field(description="数据库文件路径")
    admin_token_set: bool = Field(description="是否已设置管理令牌")


class ConfigUpdateRequest(BaseModel):
    """``PUT /api/config`` 请求体；字段为 ``None`` 表示不修改。

    Attributes:
        app_id: 新 AppID。
        app_secret: 新 AppSecret 明文（仅本次传输，不落日志、不回显）。
        host: 新监听地址。
        port: 新监听端口。
        log_level: 新日志级别。
        db_path: 新数据库文件路径。
    """

    model_config = ConfigDict(extra="forbid")

    app_id: str | None = Field(default=None, min_length=1, description="新 AppID")
    app_secret: str | None = Field(default=None, description="新 AppSecret")
    host: str | None = Field(default=None, description="新监听地址")
    port: int | None = Field(default=None, ge=1, le=65535, description="新监听端口")
    log_level: LogLevel | None = Field(default=None, description="新日志级别")
    db_path: str | None = Field(default=None, description="新数据库文件路径")


# ---------------------------------------------------------------- 首次配置向导


class SetupStatusResponse(BaseModel):
    """``GET /api/setup/status`` 响应（无需鉴权）。

    Attributes:
        configured: 必填项（app_id / app_secret）是否均已填写。
        missing: 缺失的必填键名小写列表；完全已配置时为空。
    """

    configured: bool = Field(description="必填项是否已全部填写")
    missing: list[str] = Field(description="缺失的必填键名（app_id / app_secret）")


class SetupRequest(BaseModel):
    """``POST /api/setup`` 请求体。

    Attributes:
        app_id: QQ 开放平台 AppID。
        app_secret: QQ 开放平台 AppSecret 明文（仅本次传输）。
    """

    model_config = ConfigDict(extra="forbid")

    app_id: str = Field(min_length=1, description="QQ 开放平台 AppID")
    app_secret: str = Field(min_length=1, description="QQ 开放平台 AppSecret")


class SetupResponse(BaseModel):
    """``POST /api/setup`` 响应。

    注意：``admin_token`` **只在首次配置（configured=false→true 的那一次）返回明文**。
    一旦 .env 原本已有 ADMIN_TOKEN，响应中此字段必为 ``None``，改由 ``token_already_existed``
    告知前端"令牌已存在，请自行去 .env 查看"。这是框架唯一一次返回明文令牌的接口。
    """

    model_config = ConfigDict(extra="forbid")

    configured: bool = Field(description="已配置完成")
    admin_token: str | None = Field(
        default=None,
        description="本次新生成的管理令牌明文（仅首次配置时可能返回）。",
    )
    token_already_existed: bool = Field(
        default=False,
        description=".env 原本已有 ADMIN_TOKEN 时为 True（此时 admin_token 必为 None）。",
    )
    restart_required: bool = Field(description="需要重启才生效")


class BotStatusResponse(BaseModel):
    """``GET /api/bot`` 响应。"""

    running: bool = Field(description="Bot 当前是否正在运行")


class BotActionResult(BaseModel):
    """``POST /api/bot/start|stop`` 响应。"""

    started: bool = Field(description="启动请求是否成功（stop 固定为 False）")
    error: str | None = Field(default=None, description="失败时的错误信息")
