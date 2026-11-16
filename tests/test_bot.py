"""core/bot.py 的单元测试。

全程使用 FakeClient（monkeypatch 替换 ``core.bot.botpy.Client``），
不发网络请求、不读 .env。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import core.bot
from core.bot import QminBot
from core.events import GroupAtMessage
from core.state import get_state, reset_state


class FakeAPI:
    """记录 post_group_message 调用的假 API。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def post_group_message(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"ok": True}


class FakeClient:
    """假 botpy.Client：记录启动/关闭，暴露假 api。"""

    instances: list[FakeClient] = []

    def __init__(
        self,
        *,
        intents: Any = None,
        is_sandbox: bool = False,
        rate_limit: Any = None,
        **kwargs: Any,
    ) -> None:
        self.intents = intents
        self.is_sandbox = is_sandbox
        self.rate_limit = rate_limit
        self.api = FakeAPI()
        self.on_message = None
        self.on_ready = None
        self.started = False
        self.closed = False
        FakeClient.instances.append(self)

    async def start(self, appid: str, secret: str, ret_coro: bool = False) -> None:
        self.started = True
        if self.on_ready is not None:
            await self.on_ready()
        return None

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def patched_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个用例替换 Client 并重置状态。"""
    reset_state()
    FakeClient.instances.clear()
    monkeypatch.setattr(core.bot.botpy, "Client", FakeClient)
    yield
    reset_state()


def make_inbound(scope: str = "group") -> SimpleNamespace:
    """构造与 InboundMessage 字段对齐的假入站消息。"""
    return SimpleNamespace(
        id="msg-1",
        content="你好",
        author_id="user-1",
        author_name="小明",
        timestamp="2026-11-16T00:00:00Z",
        raw={"id": "msg-1"},
        reply_target=SimpleNamespace(scope=scope, target_id="group-1"),
    )


async def test_start_sets_connected_without_calling_api() -> None:
    """start 经 on_ready 置连接状态，且不调用业务 API。"""
    bot = QminBot(app_id="100", app_secret="secret")

    await bot.start()

    fake = FakeClient.instances[-1]
    assert fake.started is True
    assert fake.api.calls == []
    state = get_state()
    assert state.connected is True
    assert any("网关已就绪" in entry.message for entry in state.recent_logs())
    assert any("正在连接" in entry.message for entry in state.recent_logs())


async def test_start_failure_is_logged_and_reraised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """start 抛异常时记录 ERROR 日志并原样抛出。"""

    class FailingClient(FakeClient):
        async def start(self, appid: str, secret: str, ret_coro: bool = False) -> None:
            raise RuntimeError("connect failed")

    monkeypatch.setattr(core.bot.botpy, "Client", FailingClient)
    bot = QminBot(app_id="1", app_secret="s")

    with pytest.raises(RuntimeError):
        await bot.start()

    errors = [entry for entry in get_state().recent_logs() if entry.level == "ERROR"]
    assert len(errors) == 1
    assert "RuntimeError" in errors[0].message


async def test_group_message_is_dispatched_with_fields() -> None:
    """群消息会构造 GroupAtMessage 并交给 dispatcher，字段正确。"""
    received: list[GroupAtMessage] = []

    async def dispatcher(event: GroupAtMessage) -> None:
        received.append(event)

    bot = QminBot(app_id="1", app_secret="s", dispatcher=dispatcher)

    await bot._on_message(make_inbound("group"))

    assert len(received) == 1
    event = received[0]
    assert isinstance(event, GroupAtMessage)
    assert event.group_openid == "group-1"
    assert event.content == "你好"
    assert event.sender_id == "user-1"
    assert event.sender_name == "小明"
    assert event.msg_id == "msg-1"
    assert event.timestamp == "2026-11-16T00:00:00Z"
    assert event.raw == {"id": "msg-1"}


async def test_c2c_message_is_ignored() -> None:
    """非群聊消息不会调用 dispatcher。"""
    received: list[GroupAtMessage] = []

    async def dispatcher(event: GroupAtMessage) -> None:
        received.append(event)

    bot = QminBot(app_id="1", app_secret="s", dispatcher=dispatcher)

    await bot._on_message(make_inbound("c2c"))

    assert received == []


async def test_dispatcher_exception_is_isolated() -> None:
    """dispatcher 抛异常不冒泡，ERROR 日志含异常类型名。"""

    async def dispatcher(event: GroupAtMessage) -> None:
        raise ValueError("boom")

    bot = QminBot(app_id="1", app_secret="s", dispatcher=dispatcher)

    await bot._on_message(make_inbound("group"))

    errors = [entry for entry in get_state().recent_logs() if entry.level == "ERROR"]
    assert len(errors) == 1
    assert "ValueError" in errors[0].message
    assert "boom" in errors[0].message


async def test_send_group_text_passes_expected_kwargs() -> None:
    """send_group_text 只传 group_openid / content / msg_id，不传 msg_seq。"""
    bot = QminBot(app_id="1", app_secret="s")

    result = await bot.send_group_text("group-1", "hi", msg_id="msg-9")

    assert result == {"ok": True}
    call = FakeClient.instances[-1].api.calls[0]
    assert call["group_openid"] == "group-1"
    assert call["content"] == "hi"
    assert call["msg_id"] == "msg-9"
    assert "msg_seq" not in call


async def test_malformed_inbound_is_logged_without_raising() -> None:
    """缺少 target_id 的入站消息只记 ERROR 日志，不向外抛异常。"""
    bot = QminBot(app_id="1", app_secret="s")
    inbound = SimpleNamespace(
        id="msg-1",
        content="你好",
        author_id="user-1",
        author_name="小明",
        timestamp=None,
        raw={},
        reply_target=SimpleNamespace(scope="group"),
    )

    await bot._on_message(inbound)

    errors = [entry for entry in get_state().recent_logs() if entry.level == "ERROR"]
    assert len(errors) == 1
    assert "事件构造失败" in errors[0].message
    assert "AttributeError" in errors[0].message


async def test_rate_limit_is_passed_to_client() -> None:
    """rate_limit 参数原样透传给 botpy.Client。"""
    sentinel = {"certification": "unverified"}

    QminBot(app_id="1", app_secret="s", rate_limit=sentinel)

    assert FakeClient.instances[-1].rate_limit is sentinel


async def test_rate_limit_defaults_to_none() -> None:
    """未传 rate_limit 时 Client 收到 None。"""
    QminBot(app_id="1", app_secret="s")

    assert FakeClient.instances[-1].rate_limit is None
