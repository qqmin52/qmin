"""语义化事件模型。

只定义框架对外暴露的事件对象，不 import botpy。
事件对象持有原始载荷副本与一个回复闭包，回复的具体参数（msg_id / msg_seq）
由上层 QminBot 与 SDK 负责，本层不做拼装。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


class ReplyTargetLike(Protocol):
    """回复目标的最小结构（与 botpy ReplyTarget 字段对齐）。"""

    scope: str
    target_id: str


class InboundMessageLike(Protocol):
    """botpy InboundMessage 的最小结构，避免 core/events 依赖 botpy。"""

    id: str
    content: str
    author_id: str | None
    author_name: str | None
    timestamp: str | None
    raw: Mapping[str, Any]
    reply_target: ReplyTargetLike


@dataclass(slots=True, frozen=True)
class GroupAtMessage:
    """群聊 @ 机器人消息。

    Attributes:
        group_openid: 群 openid。
        content: 消息正文。
        sender_id: 发送者 openid。
        sender_name: 发送者昵称，可能为空字符串。
        msg_id: 本次消息 id。
        timestamp: 消息时间字符串，可能为 ``None``。
        raw: 原始载荷副本。
        _replier: 回复闭包，由上层注入，不参与比较与打印。
    """

    group_openid: str
    content: str
    sender_id: str
    sender_name: str
    msg_id: str
    timestamp: str | None
    raw: Mapping[str, Any]
    _replier: Callable[[str], Awaitable[Any]] = field(repr=False, compare=False)

    async def reply(self, content: str) -> Any:
        """发送被动回复；msg_id 与 msg_seq 由上层/SDK 处理，本层不拼参数。"""
        return await self._replier(content)


def build_group_at_message(
    inbound: InboundMessageLike,
    replier: Callable[[str], Awaitable[Any]],
) -> GroupAtMessage | None:
    """把 SDK 的统一入站消息转换为群 @ 事件。

    Args:
        inbound: SDK 传入的 InboundMessage（仅使用协议中声明的字段）。
        replier: 回复闭包，接收正文并返回 SDK 的发送结果。

    Returns:
        群聊消息返回 :class:`GroupAtMessage`；非群聊（如 c2c）返回 ``None``。
    """
    if inbound.reply_target.scope != "group":
        return None

    return GroupAtMessage(
        group_openid=inbound.reply_target.target_id,
        content=inbound.content,
        sender_id=inbound.author_id or "",
        sender_name=inbound.author_name or "",
        msg_id=inbound.id,
        timestamp=inbound.timestamp,
        raw=inbound.raw,
        _replier=replier,
    )
