"""core/logstore.py 的测试。

只用 ``tmp_path`` 下的临时数据库，绝不碰真实 qmin.db。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from core.logstore import LogStore
from core.state import LogEntry


def _entry(message: str, *, level: str = "INFO", source: str = "test") -> LogEntry:
    """构造一条测试日志（seq 由调用方决定，落库时数据库会重新分配）。"""
    return LogEntry(
        seq=0,
        time=datetime.now(timezone.utc),
        level=level,  # type: ignore[arg-type]
        source=source,
        message=message,
    )


async def _write(store: LogStore, messages: list[str], **kwargs: str) -> None:
    for message in messages:
        store.enqueue(_entry(message, **kwargs))  # type: ignore[arg-type]
    await store.flush()


async def test_write_then_query_returns_items_and_latest_seq(tmp_path: Path) -> None:
    """写入后能查到，latest_seq 为数据库真实最大序号。"""
    store = LogStore(tmp_path / "logs.db")
    await store.open()

    await _write(store, ["第一条", "第二条", "第三条"])
    result = await store.query()

    assert [item.message for item in result["items"]] == ["第一条", "第二条", "第三条"]
    assert result["latest_seq"] == 3
    assert result["buffer_total"] == 3
    await store.close()


async def test_history_survives_reopen(tmp_path: Path) -> None:
    """close 后重新 open 同一文件，历史还在（重启不丢）。"""
    db = tmp_path / "logs.db"
    store = LogStore(db)
    await store.open()
    await _write(store, ["持久化日志"])
    await store.close()

    reopened = LogStore(db)
    await reopened.open()
    result = await reopened.query()
    assert [item.message for item in result["items"]] == ["持久化日志"]
    assert result["latest_seq"] == 1
    await reopened.close()


async def test_retention_keeps_only_latest_rows(tmp_path: Path) -> None:
    """max_rows=5 时写 10 条，只剩最后 5 条。"""
    store = LogStore(tmp_path / "logs.db", max_rows=5)
    await store.open()

    await _write(store, [f"m{i}" for i in range(10)])
    result = await store.query(limit=50)

    assert [item.message for item in result["items"]] == [f"m{i}" for i in range(5, 10)]
    assert result["latest_seq"] == 10
    await store.close()


async def test_after_and_before_paging_no_dup_no_miss(tmp_path: Path) -> None:
    """after_seq / before_seq 分页结果正确且不重不漏。"""
    store = LogStore(tmp_path / "logs.db")
    await store.open()
    await _write(store, [f"m{i}" for i in range(10)])

    forward = await store.query(after_seq=3, limit=3)
    assert [item.seq for item in forward["items"]] == [4, 5, 6]

    backward = await store.query(before_seq=5, limit=2)
    assert [item.seq for item in backward["items"]] == [3, 4]

    first_page = await store.query(limit=4)
    assert [item.seq for item in first_page["items"]] == [7, 8, 9, 10]
    await store.close()


async def test_level_source_and_keyword_filters(tmp_path: Path) -> None:
    """level / source 精确匹配、q 关键词模糊匹配生效。"""
    store = LogStore(tmp_path / "logs.db")
    await store.open()

    store.enqueue(_entry("普通消息", level="INFO", source="bot"))
    store.enqueue(_entry("出错了 AuthenticationError", level="ERROR", source="bot"))
    store.enqueue(_entry("插件警告", level="WARNING", source="plugin"))
    await store.flush()

    by_level = await store.query(level="ERROR")
    assert [item.message for item in by_level["items"]] == ["出错了 AuthenticationError"]

    by_source = await store.query(source="plugin")
    assert [item.message for item in by_source["items"]] == ["插件警告"]

    by_keyword = await store.query(q="AuthenticationError")
    assert [item.level for item in by_keyword["items"]] == ["ERROR"]
    await store.close()


async def test_latest_seq_is_zero_for_empty_table(tmp_path: Path) -> None:
    """空表时 latest_seq 为 0（不是 after_seq 回声）。"""
    store = LogStore(tmp_path / "logs.db")
    await store.open()
    result = await store.query(after_seq=999)
    assert result["items"] == []
    assert result["latest_seq"] == 0
    await store.close()


async def test_close_is_idempotent(tmp_path: Path) -> None:
    """close 可重复调用，不会抛异常。"""
    store = LogStore(tmp_path / "logs.db")
    await store.open()
    await store.close()
    await store.close()


async def test_close_writes_entire_pending_queue(tmp_path: Path) -> None:
    """未启动后台协程时，close 也要把队列里的 500 条全部写完。"""
    db = tmp_path / "logs.db"
    store = LogStore(db)
    await store.open()
    for index in range(500):
        store.enqueue(_entry(f"bulk-{index}"))

    await store.close()

    reopened = LogStore(db)
    await reopened.open()
    result = await reopened.query(limit=200)
    assert result["buffer_total"] == 500
    assert result["latest_seq"] == 500
    await reopened.close()


async def test_close_twice_with_pending_writes_is_safe(tmp_path: Path) -> None:
    """队列有待写数据时 close 两次都不报错，且数据不丢。"""
    db = tmp_path / "logs.db"
    store = LogStore(db)
    await store.open()
    for index in range(3):
        store.enqueue(_entry(f"twice-{index}"))

    await store.close()
    await store.close()

    reopened = LogStore(db)
    await reopened.open()
    result = await reopened.query()
    assert [item.message for item in result["items"]] == [
        f"twice-{index}" for index in range(3)
    ]
    await reopened.close()
