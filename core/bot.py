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
from collections.abc import Awaitable, Callable
from typing import Any

import botpy

from core import handlers
from core.events import GroupAtMessage, InboundMessageLike, build_group_at_message
from core.handlers import Router
from core.state import RuntimeState, get_state

# 旧版事件分发器：收到群 @ 消息后由框架调用。
Dispatcher = Callable[[GroupAtMessage], Awaitable[None]]


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
        """
        self._app_id = app_id
        self._app_secret = app_secret
        self._dispatcher = dispatcher
        self._router = router if router is not None else handlers.router
        self._state = state if state is not None else get_state()
        self._client = botpy.Client(
            intents=botpy.Intents(public_messages=True),
            is_sandbox=sandbox,
            rate_limit=rate_limit,
        )
        self._client.on_message = self._on_message
        self._client.on_ready = self._on_ready

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

    async def _on_message(self, inbound: InboundMessageLike) -> None:
        """SDK 消息回调入口：转换为群 @ 事件并分发给路由器。"""

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
