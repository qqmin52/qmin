"""运行时状态模块。

职责：以进程内单例的形式保存「连接状态 + 启动时间 + 插件列表 + 最近 200 条日志」，
供 ``core/`` 内部写入、``api/`` 只读暴露。这是 core 与 api 之间唯一的状态契约。

约定：

- 单例由 :func:`get_state` 懒创建，:func:`reset_state` 仅置空，供测试隔离。
- 日志缓冲区为 ``deque(maxlen=200)``，``seq`` 从 1 全局自增，超出容量丢弃最旧。
- 写操作 async 且由实例内 ``asyncio.Lock`` 保护；读操作同步返回副本。
- 内部插件与日志对象一律不直接交给调用方，避免外部改坏状态。
- 本模块不 import ``core.config`` / ``api/`` / ``botpy``，也不持有任何 token / secret。
"""

# TODO(api/schema.py 字段漂移，等实现路由时统一对齐)：
#   1. StatusSnapshot.log_count  ↔  api.schema.StatusResponse.log_seq
#   2. PluginRecord.handler_count ↔  api.schema.PluginInfo.handlers
#   3. 本模块 LogLevel 只有 DEBUG/INFO/WARNING/ERROR 四级，
#      而 api.schema.LogLevel 仍含 CRITICAL。

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Literal

# 日志环形缓冲容量，与前端轮询约定一致。
LOG_BUFFER_SIZE: int = 200

# 日志级别，仅保留框架实际使用的四级。
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


@dataclass(slots=True, frozen=True)
class LogEntry:
    """一条运行日志（不可变，可安全共享）。

    Attributes:
        seq: 从 1 开始的单调递增序号，用于前端增量轮询去重。
        time: 产生时间，UTC 带时区。
        level: 日志级别。
        source: 来源标识，如插件名、``core.bot``、``api``。
        message: 日志正文。
    """

    seq: int
    time: datetime
    level: LogLevel
    source: str
    message: str


@dataclass(slots=True)
class PluginRecord:
    """一个已发现插件的运行记录（内部可变，对外只交副本）。

    Attributes:
        name: 插件名（文件名去扩展名）。
        path: 插件文件路径。
        enabled: 是否启用。
        loaded: 是否已成功加载进当前进程。
        handler_count: 该插件注册的处理器数量。
        error: 加载或运行失败的摘要；成功时为 ``None``。
    """

    name: str
    path: str
    enabled: bool = True
    loaded: bool = False
    handler_count: int = 0
    error: str | None = None


@dataclass(slots=True, frozen=True)
class StatusSnapshot:
    """``GET /api/status`` 所需的状态快照（纯数据，不含 botpy 对象）。

    Attributes:
        connected: WebSocket 是否处于已连接状态。
        started_at: 首次连接成功的时间，未连接过为 ``None``。
        uptime_seconds: 已运行秒数；未连接时为 ``0.0``。
        plugin_total: 发现的插件总数。
        plugin_enabled: 已启用插件数。
        plugin_loaded: 已成功加载插件数。
        log_count: 当前环形缓冲中的日志条数。
    """

    connected: bool
    started_at: datetime | None
    uptime_seconds: float
    plugin_total: int
    plugin_enabled: int
    plugin_loaded: int
    log_count: int


class RuntimeState:
    """运行时状态单例的载体。

    外部只应通过 :func:`get_state` 获取实例；构造由模块内部完成。
    """

    def __init__(self) -> None:
        """初始化空状态：未连接、无启动时间、无插件、空日志缓冲。"""
        self._lock = asyncio.Lock()
        self._logs: deque[LogEntry] = deque(maxlen=LOG_BUFFER_SIZE)
        self._plugins: dict[str, PluginRecord] = {}
        self._seq: int = 0
        self._connected: bool = False
        self._started_at: datetime | None = None

    # ---------- 连接状态 ----------

    @property
    def connected(self) -> bool:
        """WebSocket 当前是否已连接。"""
        return self._connected

    @property
    def started_at(self) -> datetime | None:
        """首次连接成功的时间；从未连接过为 ``None``。"""
        return self._started_at

    async def set_connected(self, connected: bool) -> None:
        """更新连接状态；首次置 ``True`` 时记录启动时间。

        Args:
            connected: 新的连接状态。
        """
        async with self._lock:
            if connected and self._started_at is None:
                self._started_at = datetime.now(timezone.utc)
            self._connected = connected

    # ---------- 插件 ----------

    async def set_plugins(self, plugins: list[PluginRecord]) -> None:
        """整体替换插件列表（插件热扫描后调用）。

        Args:
            plugins: 最新的插件记录；内部存副本，调用方后续改动不影响状态。
        """
        async with self._lock:
            self._plugins = {record.name: replace(record) for record in plugins}

    def list_plugins(self) -> list[PluginRecord]:
        """返回插件记录副本列表（保持 ``set_plugins`` 的传入顺序）。"""
        return [replace(record) for record in self._plugins.values()]

    async def toggle_plugin(self, name: str, enabled: bool) -> PluginRecord:
        """切换插件启用状态。

        Args:
            name: 插件名。
            enabled: 目标状态。

        Returns:
            更新后的插件记录副本。

        Raises:
            KeyError: 插件不存在。
        """
        async with self._lock:
            record = self._plugins.get(name)
            if record is None:
                raise KeyError(name)
            updated = replace(record, enabled=enabled)
            self._plugins[name] = updated
            return replace(updated)

    # ---------- 日志 ----------

    async def add_log(self, level: LogLevel, source: str, message: str) -> LogEntry:
        """写入一条日志到环形缓冲。

        Args:
            level: 日志级别。
            source: 来源标识。
            message: 日志正文。

        Returns:
            写入后的日志记录（含分配到的 ``seq``）。
        """
        async with self._lock:
            self._seq += 1
            entry = LogEntry(
                seq=self._seq,
                time=datetime.now(timezone.utc),
                level=level,
                source=source,
                message=message,
            )
            self._logs.append(entry)
            return entry

    def recent_logs(self, limit: int = LOG_BUFFER_SIZE) -> list[LogEntry]:
        """按时间升序返回最近的日志，最新的一条在末尾。

        Args:
            limit: 最多返回条数；``<= 0`` 返回空列表，超过实际条数时按实际截断。
        """
        if limit <= 0:
            return []
        entries = list(self._logs)
        if limit >= len(entries):
            return entries
        return entries[-limit:]

    # ---------- 快照 ----------

    def snapshot(self) -> StatusSnapshot:
        """汇总当前状态，供 ``GET /api/status`` 使用。"""
        return StatusSnapshot(
            connected=self._connected,
            started_at=self._started_at,
            uptime_seconds=self._uptime_seconds(),
            plugin_total=len(self._plugins),
            plugin_enabled=sum(1 for record in self._plugins.values() if record.enabled),
            plugin_loaded=sum(1 for record in self._plugins.values() if record.loaded),
            log_count=len(self._logs),
        )

    def _uptime_seconds(self) -> float:
        """计算已运行秒数；未连接或未启动时返回 ``0.0``。"""
        if not self._connected or self._started_at is None:
            return 0.0
        elapsed = (datetime.now(timezone.utc) - self._started_at).total_seconds()
        return max(elapsed, 0.0)


_state: RuntimeState | None = None


def get_state() -> RuntimeState:
    """获取运行时状态单例（首次调用时创建）。

    Returns:
        进程内唯一的 :class:`RuntimeState`。
    """
    global _state
    if _state is None:
        _state = RuntimeState()
    return _state


def reset_state() -> None:
    """销毁单例，仅用于测试用例之间隔离。

    Notes:
        只置空模块级引用；锁与数据随旧实例一起丢弃。
        生产代码禁止调用。
    """
    global _state
    _state = None
