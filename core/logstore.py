"""日志持久化：把运行时日志写入 SQLite，重启不丢、可分页检索。

设计要点：

- :meth:`LogStore.enqueue` 是同步、非阻塞的——只把条目推入内存队列，
  绝不做 I/O，因此可以安全地挂在 :meth:`core.state.RuntimeState.add_log` 的
  sink 上（sink 必须是同步函数）。
- :meth:`LogStore.run` 是后台协程，每 0.5 秒或累计 200 条就批量写库；
  单条写入失败只打印 stderr 并计数，绝不抛出——落库故障不能拖垮机器人与面板。
- 保留策略按 ``max_rows`` 裁剪最旧记录，每 20 次 flush 或累计行数达到上限时执行。
- :meth:`LogStore.query` 支持 after_seq / before_seq 分页与 level / source / 关键词过滤，
  所有参数均走 SQL 占位符，禁止字符串拼接。
- 同时顺带消费 botpy 的 SDK 日志队列（见 :data:`SDK_LOG_QUEUE`），
  把它转成 ``source="sdk"`` 的运行日志。
"""

from __future__ import annotations

import asyncio
import queue
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import aiosqlite

from core.state import LogEntry, get_state

# botpy 的 logging.Handler 只往这里塞 (levelname, message)，不直接触碰事件循环。
# 由 LogStore.run() 在事件循环里消费，避免跨线程 await。
SDK_LOG_QUEUE: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS logs (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    source TEXT NOT NULL,
    message TEXT NOT NULL
)
"""

_INSERT = "INSERT INTO logs (ts, level, source, message) VALUES (?, ?, ?, ?)"

_VALID_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR"}


class LogStoreError(RuntimeError):
    """日志库打开、读写失败时抛出；调用方据此降级到内存模式。"""


class LogStore:
    """SQLite 日志存储。

    Args:
        db_path: SQLite 文件路径。
        max_rows: 最多保留的行数，超出后裁掉最旧记录。
        sdk_mode: SDK 日志级别策略，``"off"`` 只导 WARNING 及以上，``"all"`` 也导 INFO。
    """

    FLUSH_INTERVAL = 0.5
    BATCH_SIZE = 200
    POLL_INTERVAL = 0.1
    RETENTION_EVERY = 20
    MAX_PENDING = 10000

    def __init__(
        self,
        db_path: Path,
        max_rows: int = 50000,
        *,
        sdk_mode: Literal["off", "all"] = "off",
    ) -> None:
        self._db_path = Path(db_path)
        self._max_rows = max(int(max_rows), 1)
        self._sdk_mode = sdk_mode
        self._conn: aiosqlite.Connection | None = None
        self._queue: deque[LogEntry] = deque(maxlen=self.MAX_PENDING)
        self._queue_lock = threading.Lock()
        self._run_task: asyncio.Task[Any] | None = None
        self._stop = False
        self._flushes = 0
        self._rows_since_retention = 0
        self.write_errors = 0

    # ---------- 生命周期 ----------

    async def open(self) -> None:
        """打开数据库并建表；可重复调用。

        Raises:
            LogStoreError: 连接或建表失败。
        """
        if self._conn is not None:
            return
        conn: aiosqlite.Connection | None = None
        try:
            conn = await aiosqlite.connect(self._db_path)
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute(_CREATE_TABLE)
            await conn.commit()
        except Exception as exc:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass
            raise LogStoreError(
                f"打开日志库失败：{type(exc).__name__}: {exc}"
            ) from None
        self._conn = conn
        self._stop = False

    async def close(self) -> None:
        """停止后台协程、写完队列剩余条目并关闭连接；可重复调用。"""
        self._stop = True
        task, self._run_task = self._run_task, None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        # 把队列写空：最多 50 轮，防止库损坏时死循环。
        for _ in range(50):
            while self._pending():
                try:
                    await self._flush(limit=None)
                except Exception:
                    pass
            if not self._pending():
                break
            # 让出事件循环，避免长时间占用导致无法继续入队/收敛。
            await asyncio.sleep(0)

        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass

    async def run(self) -> None:
        """后台写入协程：定时批量 flush，并消费 SDK 日志队列。

        可安全地被重复创建（若已有存活的 run 任务则直接返回）。
        """
        task = asyncio.current_task()
        if (
            self._run_task is not None
            and self._run_task is not task
            and not self._run_task.done()
        ):
            return
        self._run_task = task
        loop = asyncio.get_running_loop()
        last_flush = loop.time()
        try:
            while not self._stop:
                await asyncio.sleep(self.POLL_INTERVAL)
                await self._drain_sdk_queue()
                now = loop.time()
                if (
                    self._pending() >= self.BATCH_SIZE
                    or now - last_flush >= self.FLUSH_INTERVAL
                ):
                    await self._flush()
                    last_flush = now
        except asyncio.CancelledError:
            raise

    # ---------- 写入 ----------

    def enqueue(self, entry: LogEntry) -> None:
        """同步、非阻塞地把日志条目放进待写队列。"""
        with self._queue_lock:
            self._queue.append(entry)

    def _pending(self) -> int:
        with self._queue_lock:
            return len(self._queue)

    async def flush(self) -> None:
        """立即把队列中的日志写入数据库（测试与优雅退出用）。"""
        await self._flush()

    def _take_batch(self, limit: int | None = None) -> list[LogEntry]:
        with self._queue_lock:
            count = len(self._queue) if limit is None else min(limit, len(self._queue))
            batch = [self._queue.popleft() for _ in range(count)]
        return batch

    async def _flush(self, limit: int | None = BATCH_SIZE) -> None:
        """把队列里的条目批量写入数据库；任何失败只记录，不抛出。

        Args:
            limit: 本次最多取的条数；``None`` 表示取空整个队列（``close()`` 用）。
        """
        conn = self._conn
        if conn is None:
            return

        batch = self._take_batch(limit)
        if not batch:
            return

        rows = [
            (entry.time.isoformat(), entry.level, entry.source, entry.message)
            for entry in batch
        ]
        try:
            await conn.executemany(_INSERT, rows)
            await conn.commit()
        except Exception:
            # 批量失败：逐条重试，单条失败只计数 + stderr，绝不抛出。
            for row in rows:
                try:
                    await conn.execute(_INSERT, row)
                    await conn.commit()
                    self._rows_since_retention += 1
                except Exception as exc:
                    self.write_errors += 1
                    print(
                        f"[logstore] 写入日志失败：{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
            return

        self._flushes += 1
        self._rows_since_retention += len(rows)
        if (
            self._flushes % self.RETENTION_EVERY == 0
            or self._rows_since_retention >= self._max_rows
        ):
            await self._retention()

    async def _retention(self) -> None:
        """裁掉最旧的记录，最多保留 ``max_rows`` 行。"""
        conn = self._conn
        if conn is None:
            return
        try:
            await conn.execute(
                "DELETE FROM logs WHERE seq <= (SELECT MAX(seq) FROM logs) - ?",
                (self._max_rows,),
            )
            await conn.commit()
            self._rows_since_retention = 0
        except Exception as exc:
            self.write_errors += 1
            print(
                f"[logstore] 清理旧日志失败：{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    async def _drain_sdk_queue(self) -> None:
        """把 SDK 日志转成运行日志（级别策略由 ``sdk_mode`` 决定）。"""
        state = get_state()
        while True:
            try:
                levelname, message = SDK_LOG_QUEUE.get_nowait()
            except queue.Empty:
                return
            level = self._map_sdk_level(levelname)
            if level is None:
                continue
            try:
                await state.add_log(level, "sdk", self._format_sdk_message(message))
            except Exception:
                pass

    @staticmethod
    def _format_sdk_message(message: str) -> str:
        """给 SDK 日志加 ``[botpy]`` 前缀；已有前缀（忽略大小写与空白）时不重复加。"""
        text = (message or "").strip()
        if text.lower().startswith("[botpy]"):
            return text
        return f"[botpy] {text}"

    def _map_sdk_level(self, levelname: str) -> str | None:
        name = (levelname or "").upper()
        if name in {"ERROR", "CRITICAL"}:
            return "ERROR"
        if name == "WARNING":
            return "WARNING"
        if name in {"INFO", "DEBUG"} and self._sdk_mode == "all":
            return "INFO"
        return None

    # ---------- 查询 ----------

    async def query(
        self,
        after_seq: int = 0,
        before_seq: int | None = None,
        limit: int = 200,
        level: str | None = None,
        source: str | None = None,
        q: str | None = None,
    ) -> dict[str, Any]:
        """分页查询日志。

        Args:
            after_seq: 排他向后取（``seq > after_seq``），用于增量轮询。
            before_seq: 排他向前取（``seq < before_seq``），用于"加载更早"。
            limit: 最多返回条数。
            level: 级别精确匹配。
            source: 来源精确匹配。
            q: 关键词，按 ``message LIKE %q%`` 匹配。

        Returns:
            ``{"items": list[LogEntry], "latest_seq": int, "total": int, "buffer_total": int}``。

        Raises:
            LogStoreError: 数据库未打开或查询失败。
        """
        conn = self._conn
        if conn is None:
            raise LogStoreError("日志库未打开")

        sql_limit = max(int(limit), 0)
        where: list[str] = []
        params: list[Any] = []
        if before_seq is not None:
            where.append("seq < ?")
            params.append(before_seq)
        elif after_seq:
            where.append("seq > ?")
            params.append(after_seq)
        if level:
            where.append("level = ?")
            params.append(level.upper())
        if source:
            where.append("source = ?")
            params.append(source)
        if q:
            where.append("message LIKE ?")
            params.append(f"%{q}%")
        clause = (" WHERE " + " AND ".join(where)) if where else ""

        # before_seq 或"无 after_seq 的首页"都取最新 N 条，再反转成正序返回。
        descending = before_seq is not None or not after_seq
        order = "DESC" if descending else "ASC"

        try:
            cursor = await conn.execute(
                "SELECT seq, ts, level, source, message FROM logs"
                f"{clause} ORDER BY seq {order} LIMIT ?",
                (*params, sql_limit),
            )
            rows = await cursor.fetchall()
            await cursor.close()

            latest_cursor = await conn.execute("SELECT MAX(seq) FROM logs")
            latest_row = await latest_cursor.fetchone()
            await latest_cursor.close()
            latest_seq = int(latest_row[0] or 0) if latest_row else 0

            count_cursor = await conn.execute("SELECT COUNT(*) FROM logs")
            count_row = await count_cursor.fetchone()
            await count_cursor.close()
            buffer_total = int(count_row[0] or 0) if count_row else 0
        except Exception as exc:
            raise LogStoreError(
                f"查询日志失败：{type(exc).__name__}: {exc}"
            ) from None

        if descending:
            rows = list(reversed(rows))

        items: list[LogEntry] = []
        for seq, ts, row_level, row_source, message in rows:
            if row_level not in _VALID_LEVELS:
                continue
            items.append(
                LogEntry(
                    seq=int(seq),
                    time=self._parse_ts(ts),
                    level=row_level,
                    source=row_source,
                    message=message,
                )
            )
        return {
            "items": items,
            "latest_seq": latest_seq,
            "total": len(items),
            "buffer_total": buffer_total,
        }

    @staticmethod
    def _parse_ts(value: str) -> datetime:
        """解析存储的 ISO 时间；失败时退回当前时间（不抛）。"""
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return datetime.now()
