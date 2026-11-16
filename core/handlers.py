"""事件路由：按关键字把群 @ 消息分发给已注册的处理器。

只依赖 core.events 与 core.state，不 import botpy。

处理器可带来源标记（插件名），用于按插件批量卸载。
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TypeAlias

from core.events import GroupAtMessage
from core.state import get_state

# 处理器签名：接收群 @ 事件并异步执行。
Handler: TypeAlias = Callable[[GroupAtMessage], Awaitable[None]]

# 当前注册上下文中的来源（插件名）；不在插件加载过程中时为 None。
_current_source: ContextVar[str | None] = ContextVar(
    "qmin_current_source", default=None
)


@contextmanager
def plugin_source(name: str) -> Iterator[None]:
    """标记当前上下文中的处理器来源。

    Args:
        name: 来源名称，通常为插件名。

    Yields:
        ``None``；退出时恢复之前的来源。
    """
    token = _current_source.set(name)
    try:
        yield
    finally:
        _current_source.reset(token)


class Router:
    """维持注册顺序的关键字路由器。"""

    def __init__(self) -> None:
        """创建空路由表。"""
        self._routes: list[tuple[str | None, str | None, Handler]] = []

    def register(
        self,
        keyword: str | None,
        handler: Handler,
        *,
        source: str | None = None,
    ) -> None:
        """注册处理器。

        Args:
            keyword: ``None`` 表示匹配所有群 @ 消息；否则按子串匹配正文。
            handler: 处理器协程函数。
            source: 处理器来源（插件名），用于 :meth:`unregister_source`。
        """
        self._routes.append((keyword, source, handler))

    async def dispatch(self, event: GroupAtMessage) -> int:
        """按注册顺序执行全部命中的处理器。

        Args:
            event: 群 @ 消息事件。

        Returns:
            命中的处理器数量（不论执行是否抛异常）。

        Notes:
            单个处理器抛异常时记录 ERROR 日志并继续执行后续处理器。
        """
        hit_count = 0
        for keyword, _source, handler in list(self._routes):
            if keyword is not None and keyword not in event.content:
                continue
            hit_count += 1
            try:
                await handler(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await get_state().add_log(
                    "ERROR", "handler", f"{type(exc).__name__}: {exc}"
                )
        return hit_count

    def unregister_source(self, source: str) -> int:
        """移除指定来源的全部处理器。

        Args:
            source: 来源名称。

        Returns:
            被移除的处理器数量。
        """
        kept: list[tuple[str | None, str | None, Handler]] = []
        removed = 0
        for keyword, route_source, handler in self._routes:
            if route_source == source:
                removed += 1
                continue
            kept.append((keyword, route_source, handler))
        self._routes = kept
        return removed

    def count_by_source(self, source: str) -> int:
        """统计指定来源的处理器数量。

        Args:
            source: 来源名称。

        Returns:
            当前路由表中该来源的处理器数量。
        """
        return sum(1 for _keyword, route_source, _handler in self._routes if route_source == source)

    def clear(self) -> None:
        """清空路由表（测试用）。"""
        self._routes.clear()


# 模块级默认路由器，供装饰器与 QminBot 共用。
router = Router()


def on_group_at(keyword: str | None = None) -> Callable[[Handler], Handler]:
    """把处理器注册到默认路由器的装饰器。

    Args:
        keyword: ``None`` 匹配所有群 @ 消息；否则按子串匹配正文。

    Returns:
        装饰器，注册后原样返回被装饰函数（不做包装）。

    Notes:
        注册时的来源取自 :func:`plugin_source` 上下文，无上下文则为 ``None``。
    """

    def decorator(handler: Handler) -> Handler:
        router.register(keyword, handler, source=_current_source.get())
        return handler

    return decorator
