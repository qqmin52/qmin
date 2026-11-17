"""QminBot：对 botpy.Client 的薄封装。

职责：创建并绑定 SDK 客户端、启动/停止、把统一入站消息转换为语义事件、
交给 Router（或兼容旧接口的 dispatcher）分发，并把连接状态与关键日志写进 RuntimeState。

约定：

- 不实现限流、重试与 msg_seq，全部交给 SDK。
- 不 import core.config；凭据由调用方传入。
- 不继承 botpy.Client，只通过属性赋值绑定回调。
- 连接状态在 SDK 的 ``on_ready`` 回调（网关 READY 事件）里置位。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import botpy

from core import handlers
from core.events import GroupAtMessage, InboundMessageLike, build_group_at_message
from core.handlers import Router
from core.logstore import SDK_LOG_QUEUE
from core.state import RuntimeState, get_state

# 旧版事件分发器：收到群 @ 消息后由框架调用。
Dispatcher = Callable[[GroupAtMessage], Awaitable[None]]

# 入站日志是否记录消息正文；由 CLI 启动时按 Settings.log_message_content 覆盖。
_LOG_MESSAGE_CONTENT_DEFAULT: bool = True


def set_log_message_content(enabled: bool) -> None:
    """设置入站消息日志是否记录正文（进程级默认值）。

    Args:
        enabled: ``False`` 时入站日志只记录会话 ID，不记录消息内容。
    """
    global _LOG_MESSAGE_CONTENT_DEFAULT
    _LOG_MESSAGE_CONTENT_DEFAULT = bool(enabled)


class _SdkLogHandler(logging.Handler):
    """把 botpy 的日志转投到线程安全队列，由 LogStore 在事件循环里消费。

    ``logging.Handler.emit`` 可能在任意线程被调用，因此这里只做一件事：
    把 ``(levelname, message)`` 塞进 :class:`queue.SimpleQueue`。
    绝不调用 ``add_log`` / ``await`` / 任何会再次触发 logging 的东西，避免递归。
    """

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D102 - 覆写基类
        try:
            SDK_LOG_QUEUE.put((record.levelname, record.getMessage()))
        except Exception:
            pass


_sdk_handler: _SdkLogHandler | None = None


def _install_sdk_handler() -> None:
    """给 ``botpy`` logger 挂上导流 Handler（全局只挂一次，级别 INFO）。"""
    global _sdk_handler
    logger = logging.getLogger("botpy")
    # botpy 默认可能继承 root 的 WARNING 级别，先放开到 INFO 才能收到 INFO 记录。
    if logger.level > logging.INFO or logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)
    if _sdk_handler is None:
        _sdk_handler = _SdkLogHandler()
        _sdk_handler.setLevel(logging.INFO)
    if _sdk_handler not in logger.handlers:
        logger.addHandler(_sdk_handler)


class QminBot:
    """QQ 官方机器人连接与事件转发的封装。"""

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        dispatcher: Dispatcher | None = None,
        router: Router | None = None,
        state: RuntimeState | None = None,
        sandbox: bool = False,
        rate_limit: Any = None,
        log_message_content: bool | None = None,
    ) -> None:
        """创建封装对象并绑定回调。

        Args:
            app_id: QQ 开放平台 AppID。
            app_secret: QQ 开放平台 AppSecret 明文。
            dispatcher: 已废弃，请改用 ``router``；传入时优先使用它。
            router: 事件路由器；为空时使用 ``core.handlers.router``。
            state: 运行时状态；为空时使用进程单例。
            sandbox: 是否连接沙箱环境。
            rate_limit: 透传给 botpy.Client 的限流配置。
            log_message_content: 入站日志是否记录消息正文；``None`` 用进程级默认值。
        """
        self._app_id = app_id
        self._app_secret = app_secret
        self._dispatcher = dispatcher
        self._router = router if router is not None else handlers.router
        self._state = state if state is not None else get_state()
        self._log_message_content = (
            _LOG_MESSAGE_CONTENT_DEFAULT
            if log_message_content is None
            else bool(log_message_content)
        )
        self._seen_raw_events: set[str] = set()
        self._group_events_bound = False
        self._client = botpy.Client(
            intents=botpy.Intents(public_messages=True),
            is_sandbox=sandbox,
            rate_limit=rate_limit,
        )
        self._client.on_message = self._on_message
        self._client.on_ready = self._on_ready
        self._bind_group_events()
        _install_sdk_handler()

    def _bind_group_events(self) -> None:
        """绑定「机器人入群 / 退群」事件；失败时退化为 on_raw_event 兜底。"""
        try:
            self._client.on_group_add_robot = self._on_group_add_robot
            self._client.on_group_del_robot = self._on_group_del_robot
            self._group_events_bound = True
        except Exception:
            self._group_events_bound = False
        # 兜底：SDK 不认具体事件名时，从原始事件流里识别（只记一次，不刷屏）。
        try:
            self._client.on_raw_event = self._on_raw_event
        except Exception:
            pass

    async def start(self) -> None:
        """启动机器人。

        Notes:
            botpy 的 ``Client.start`` 会阻塞到连接结束；连接状态在 SDK 触发
            ``on_ready``（网关 READY）后由 :meth:`_on_ready` 置位。
        """
        try:
            await self._state.add_log("INFO", "bot", "正在连接")
            await self._client.start(self._app_id, self._app_secret)
        except Exception as exc:
            await self._state.add_log("ERROR", "bot", f"{type(exc).__name__}: {exc}")
            raise

    async def stop(self) -> None:
        """关闭连接并更新连接状态。"""
        try:
            await self._state.add_log("INFO", "bot", "机器人已停止")
        except Exception:
            pass
        await self._client.close()
        await self._state.set_connected(False)

    async def send_group_text(
        self, group_openid: str, content: str, msg_id: str | None = None
    ) -> Any:
        """发送群聊文本消息。

        Args:
            group_openid: 群 openid。
            content: 文本正文。
            msg_id: 被动回复对应的消息 id；``None`` 表示主动消息。

        Returns:
            SDK 的发送结果。

        Notes:
            ``msg_seq`` 交由 SDK 默认值处理，本层不传。
        """
        return await self._client.api.post_group_message(
            group_openid=group_openid,
            content=content,
            msg_id=msg_id,
        )

    async def _on_ready(self) -> None:
        """SDK 网关就绪回调：置连接状态并记录日志。"""
        await self._state.set_connected(True)
        await self._state.add_log("INFO", "bot", "网关已就绪")

    async def _on_group_add_robot(self, data: Any = None) -> None:
        """机器人被拉进群的事件回调。"""
        await self._log_group_event("机器人被加入群", data)

    async def _on_group_del_robot(self, data: Any = None) -> None:
        """机器人被移出群的事件回调。"""
        await self._log_group_event("机器人被移出群", data)

    async def _log_group_event(self, title: str, data: Any) -> None:
        """按统一文案记录群事件；取不到群 ID 时写"群信息不可用"。"""
        group_id = getattr(data, "group_openid", None) or getattr(data, "group_id", None)
        if group_id is None and isinstance(data, dict):
            group_id = data.get("group_openid") or data.get("group_id")
        suffix = f"群 {group_id}" if group_id else "群信息不可用"
        try:
            await self._state.add_log("INFO", "bot", f"{title} | {suffix}")
        except Exception:
            pass

    async def _on_raw_event(self, event: Any) -> None:
        """兜底：SDK 不认具体事件名时，从原始事件流里识别群事件。

        每种事件只记一条 INFO，避免刷屏；已由具体回调处理的群事件不重复记录。
        """
        name = str(getattr(event, "event_type", "") or "").upper()
        if not name:
            return
        if name.startswith("GROUP_ADD_ROBOT") or name.startswith("GROUP_DEL_ROBOT"):
            if self._group_events_bound or name in self._seen_raw_events:
                return
            self._seen_raw_events.add(name)
            title = "机器人被加入群" if "ADD" in name else "机器人被移出群"
            await self._log_group_event(title, getattr(event, "data", None))
            return
        if name in self._seen_raw_events:
            return
        self._seen_raw_events.add(name)
        try:
            await self._state.add_log("INFO", "bot", f"收到事件 {name}")
        except Exception:
            pass

    async def _on_message(self, inbound: InboundMessageLike) -> None:
        """SDK 消息回调入口：入站留痕 → 转换为群 @ 事件并分发给路由器。"""

        # 入站留痕：目标 ID 前 8 位 + 内容前 30 字，不整段落盘。
        try:
            target_id = inbound.reply_target.target_id or ""
            content = inbound.content or ""
            summary = content[:30].replace("\n", " ").strip()
            if self._log_message_content and summary:
                message = f"收到群消息 | 会话 {target_id[:8]} | 内容 {summary}"
            else:
                message = f"收到群消息 | 会话 {target_id[:8]}"
            await self._state.add_log("INFO", "bot", message)
        except Exception:
            # 写日志失败不影响后续分发。
            pass

        async def _replier(content: str) -> Any:
            return await self.send_group_text(
                inbound.reply_target.target_id, content, msg_id=inbound.id
            )

        try:
            message = build_group_at_message(inbound, _replier)
        except Exception as exc:
            await self._state.add_log(
                "ERROR", "bot", f"事件构造失败 {type(exc).__name__}: {exc}"
            )
            return

        if message is None:
            return

        if self._dispatcher is not None:
            try:
                await self._dispatcher(message)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._state.add_log(
                    "ERROR", "bot", f"{type(exc).__name__}: {exc}"
                )
            return

        await self._router.dispatch(message)
