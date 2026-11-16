"""core/handlers.py 的单元测试。

每个用例前后重置 RuntimeState 与默认路由器；端到端用例用 FakeClient 替换 SDK 客户端。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import core.bot
from core.bot import QminBot
from core.events import GroupAtMessage
from core.handlers import on_group_at, plugin_source, router
from core.state import get_state, reset_state


async def _noop_replier(content: str) -> Any:
    return {"ok": True}


def make_event(content: str = "任意内容") -> GroupAtMessage:
    """构造一个最小可用的群 @ 事件。"""
    return GroupAtMessage(
        group_openid="group-1",
        content=content,
        sender_id="user-1",
        sender_name="小明",
        msg_id="msg-1",
        timestamp=None,
        raw={},
        _replier=_noop_replier,
    )


class FakeClient:
    """假 botpy.Client，仅供端到端用例实例化 QminBot。"""

    def __init__(self, *, intents: Any = None, is_sandbox: bool = False, **kwargs: Any) -> None:
        self.intents = intents
        self.is_sandbox = is_sandbox
        self.api = SimpleNamespace()
        self.on_message = None

    async def start(self, appid: str, secret: str, ret_coro: bool = False) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.fixture(autouse=True)
def clean_router(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个用例前后清理状态与路由表，并替换 SDK 客户端。"""
    reset_state()
    router.clear()
    monkeypatch.setattr(core.bot.botpy, "Client", FakeClient)
    yield
    router.clear()
    reset_state()


async def test_no_keyword_matches_every_group_message() -> None:
    """关键字为 None 时匹配任意群 @ 消息。"""
    calls: list[GroupAtMessage] = []

    @on_group_at()
    async def handler(event: GroupAtMessage) -> None:
        calls.append(event)

    assert await router.dispatch(make_event("随便什么")) == 1
    assert len(calls) == 1


async def test_keyword_matches_only_substring() -> None:
    """关键字按子串匹配正文。"""
    calls: list[str] = []

    @on_group_at("天气")
    async def handler(event: GroupAtMessage) -> None:
        calls.append(event.content)

    assert await router.dispatch(make_event("今天天气不错")) == 1
    assert calls == ["今天天气不错"]

    assert await router.dispatch(make_event("你好")) == 0
    assert calls == ["今天天气不错"]


async def test_multiple_handlers_run_in_registration_order() -> None:
    """多个命中时按注册顺序全部执行，返回命中数。"""
    order: list[str] = []

    @on_group_at()
    async def first(event: GroupAtMessage) -> None:
        order.append("first")

    @on_group_at("天气")
    async def second(event: GroupAtMessage) -> None:
        order.append("second")

    assert await router.dispatch(make_event("天气如何")) == 2
    assert order == ["first", "second"]


async def test_handler_exception_does_not_block_next() -> None:
    """单个处理器抛异常时记录 ERROR 并继续执行后续处理器。"""
    order: list[str] = []

    @on_group_at()
    async def broken(event: GroupAtMessage) -> None:
        raise ValueError("boom")

    @on_group_at()
    async def healthy(event: GroupAtMessage) -> None:
        order.append("healthy")

    assert await router.dispatch(make_event()) == 2
    assert order == ["healthy"]

    errors = [entry for entry in get_state().recent_logs() if entry.level == "ERROR"]
    assert len(errors) == 1
    assert "ValueError" in errors[0].message
    assert errors[0].source == "handler"


async def test_clear_removes_all_handlers() -> None:
    """clear 后没有处理器命中。"""

    @on_group_at()
    async def handler(event: GroupAtMessage) -> None:
        return None

    router.clear()

    assert await router.dispatch(make_event()) == 0


async def test_bot_dispatches_to_decorated_handler() -> None:
    """QminBot 默认使用模块级 router，端到端能触发装饰器注册的处理器。"""
    calls: list[GroupAtMessage] = []

    @on_group_at()
    async def handler(event: GroupAtMessage) -> None:
        calls.append(event)

    bot = QminBot(app_id="1", app_secret="s")
    inbound = SimpleNamespace(
        id="msg-1",
        content="你好",
        author_id="user-1",
        author_name="小明",
        timestamp="2026-11-16T00:00:00Z",
        raw={"id": "msg-1"},
        reply_target=SimpleNamespace(scope="group", target_id="group-1"),
    )

    await bot._on_message(inbound)

    assert len(calls) == 1
    assert calls[0].group_openid == "group-1"
    assert calls[0].msg_id == "msg-1"


async def test_unregister_source_removes_context_handlers() -> None:
    """插件上下文中注册的处理器可按来源批量移除。"""
    calls: list[GroupAtMessage] = []

    with plugin_source("demo"):

        @on_group_at()
        async def handler(event: GroupAtMessage) -> None:
            calls.append(event)

    assert await router.dispatch(make_event()) == 1

    assert router.unregister_source("demo") == 1

    assert await router.dispatch(make_event()) == 0
    assert len(calls) == 1


async def test_unregister_source_keeps_unrelated_handlers() -> None:
    """移除来源时不影响上下文之外注册的处理器。"""
    calls: list[GroupAtMessage] = []

    @on_group_at()
    async def handler(event: GroupAtMessage) -> None:
        calls.append(event)

    assert router.unregister_source("demo") == 0

    assert await router.dispatch(make_event()) == 1
    assert len(calls) == 1
