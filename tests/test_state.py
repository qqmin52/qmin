"""core/state.py 的单元测试。

每个用例前后调用 ``reset_state()``，保证单例与序号互不污染。
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from datetime import timedelta

import pytest

from core.state import (
    LOG_BUFFER_SIZE,
    LogEntry,
    PluginRecord,
    get_state,
    reset_state,
)


@pytest.fixture(autouse=True)
def fresh_state() -> Iterator[None]:
    """用例前后各重置一次单例。"""
    reset_state()
    yield
    reset_state()


async def test_set_sink_receives_every_log_and_ring_still_works() -> None:
    """set_sink 后每条日志都投递给 sink，且仍然进入内存环形缓冲。"""
    state = get_state()
    received: list[LogEntry] = []
    state.set_sink(received.append)

    entry = await state.add_log("INFO", "test", "落盘测试")

    assert len(received) == 1
    assert received[0].message == "落盘测试"
    assert state.recent_logs()[-1] is entry
    assert state.snapshot().log_count == 1


async def test_set_sink_none_detaches() -> None:
    """传 None 后不再投递。"""
    state = get_state()
    received: list[LogEntry] = []
    state.set_sink(received.append)
    state.set_sink(None)

    await state.add_log("INFO", "test", "解除后")

    assert received == []
    assert state.snapshot().log_count == 1


async def test_sink_exception_does_not_break_add_log() -> None:
    """sink 抛异常不能影响日志写入方。"""
    state = get_state()

    def boom(_entry: LogEntry) -> None:
        raise RuntimeError("sink failed")

    state.set_sink(boom)
    entry = await state.add_log("INFO", "test", "仍然写入")
    assert entry.message == "仍然写入"
    assert state.snapshot().log_count == 1


def test_singleton_returns_same_object_and_reset_creates_new() -> None:
    """get_state 多次调用返回同一对象；reset_state 之后是新对象。"""
    first = get_state()
    assert get_state() is first

    reset_state()
    second = get_state()

    assert second is not first


async def test_log_ring_buffer_keeps_latest_200() -> None:
    """写 250 条后只保留后 200 条，序号从 51 到 250。"""
    state = get_state()

    for index in range(250):
        await state.add_log("INFO", "test", f"line-{index + 1}")

    logs = state.recent_logs(LOG_BUFFER_SIZE)

    assert len(logs) == 200
    assert logs[0].seq == 51
    assert logs[-1].seq == 250
    assert [entry.seq for entry in logs] == list(range(51, 251))
    assert state.snapshot().log_count == 200


async def test_concurrent_add_log_produces_unique_sequential_seq() -> None:
    """50 个并发 add_log 的 seq 恰为 1..50，无重复。"""
    state = get_state()

    await asyncio.gather(
        *(state.add_log("INFO", "test", f"concurrent-{index}") for index in range(50))
    )

    logs = state.recent_logs(LOG_BUFFER_SIZE)

    assert len(logs) == 50
    assert [entry.seq for entry in logs] == list(range(1, 51))
    assert len({entry.seq for entry in logs}) == 50


async def test_toggle_missing_plugin_raises_key_error() -> None:
    """toggle_plugin 对不存在的插件抛 KeyError。"""
    state = get_state()

    with pytest.raises(KeyError):
        await state.toggle_plugin("not-exists", False)


async def test_set_plugins_counts_in_snapshot() -> None:
    """set_plugins 后 snapshot 的总数 / 启用数 / 加载数正确。"""
    state = get_state()
    await state.set_plugins(
        [
            PluginRecord(
                name="alpha",
                path="plugins/alpha.py",
                enabled=True,
                loaded=True,
                handler_count=2,
            ),
            PluginRecord(name="beta", path="plugins/beta.py", enabled=True, loaded=False),
            PluginRecord(name="gamma", path="plugins/gamma.py", enabled=False, loaded=False),
        ]
    )

    snapshot = state.snapshot()

    assert snapshot.plugin_total == 3
    assert snapshot.plugin_enabled == 2
    assert snapshot.plugin_loaded == 1
    assert snapshot.log_count == 0


async def test_uptime_is_zero_before_connect_and_tracked_after() -> None:
    """未连接时 uptime 为 0；连接后 started_at 非空且 uptime >= 0。"""
    state = get_state()

    assert state.snapshot().uptime_seconds == 0.0
    assert state.started_at is None

    await state.set_connected(True)
    snapshot = state.snapshot()

    assert snapshot.connected is True
    assert snapshot.started_at is not None
    assert snapshot.uptime_seconds >= 0.0

    started_at = state.started_at
    assert started_at is not None
    await state.set_connected(False)

    # 新语义：disconnected 后 started_at 清为 None（运行时长归 0）
    assert state.started_at is None
    assert state.snapshot().uptime_seconds == 0.0

    # 再连接 → started_at 重新记时间
    await state.set_connected(True)
    assert state.started_at is not None
    assert state.started_at >= started_at  # 时间向后推进


async def test_reset_state_restarts_seq_from_one() -> None:
    """reset_state 之后 seq 从 1 重新开始，启动时间清空。"""
    state = get_state()
    await state.add_log("INFO", "test", "before-reset")
    await state.set_connected(True)
    assert state.recent_logs()[-1].seq == 1

    reset_state()
    new_state = get_state()

    assert new_state is not state
    assert new_state.started_at is None
    entry = await new_state.add_log("INFO", "test", "after-reset")
    assert entry.seq == 1


async def test_log_entry_time_is_utc_aware() -> None:
    """LogEntry.time 带 UTC 时区，且是 frozen dataclass。"""
    entry = await get_state().add_log("INFO", "test", "hello")

    assert isinstance(entry, LogEntry)
    assert entry.time.tzinfo is not None
    assert entry.time.utcoffset() == timedelta(0)
    with pytest.raises(Exception):
        entry.seq = 999  # type: ignore[misc]


async def test_recent_logs_limit_edges() -> None:
    """limit <= 0 返回空列表；limit 超长时按实际条数截断。"""
    state = get_state()
    for index in range(3):
        await state.add_log("INFO", "test", f"edge-{index}")

    assert state.recent_logs(0) == []
    assert state.recent_logs(-1) == []
    assert len(state.recent_logs(999)) == 3
    assert [entry.message for entry in state.recent_logs(2)] == ["edge-1", "edge-2"]


async def test_plugins_are_defensive_copies() -> None:
    """set_plugins / list_plugins / toggle_plugin 均不泄漏内部可变对象。"""
    state = get_state()
    original = PluginRecord(name="alpha", path="plugins/alpha.py", enabled=True)
    await state.set_plugins([original])

    original.enabled = False
    assert state.list_plugins()[0].enabled is True

    listed = state.list_plugins()
    listed[0].enabled = False
    assert state.list_plugins()[0].enabled is True

    returned = await state.toggle_plugin("alpha", False)
    returned.enabled = True
    assert state.list_plugins()[0].enabled is False
