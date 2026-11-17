"""运行日志接口：优先查 SQLite（可翻历史），失败时回退内存环形缓冲。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from api.deps import make_admin_token_dependency
from api.schema import LogItem, LogsResponse
from core.config import Settings
from core.logstore import LogStore, LogStoreError
from core.state import LogEntry, get_state

# 单次最多返回的日志条数。
MAX_LOG_LIMIT: int = 200


def _to_items(entries: list[LogEntry]) -> list[LogItem]:
    """把内部日志条目转成响应模型。"""
    return [
        LogItem(
            seq=entry.seq,
            time=entry.time,
            level=entry.level,
            source=entry.source,
            message=entry.message,
        )
        for entry in entries
    ]


def _query_memory(
    *,
    after_seq: int,
    before_seq: int | None,
    limit: int,
    level: str | None,
    source: str | None,
    q: str | None,
) -> tuple[list[LogEntry], int]:
    """内存回退查询：保持 after_seq 语义，同时支持 before_seq 与过滤。"""
    entries = list(get_state().recent_logs(MAX_LOG_LIMIT))
    latest_seq = entries[-1].seq if entries else 0

    filtered = entries
    if level:
        wanted = level.upper()
        filtered = [e for e in filtered if e.level == wanted]
    if source:
        filtered = [e for e in filtered if e.source == source]
    if q:
        filtered = [e for e in filtered if q in e.message]
    if before_seq is not None:
        filtered = [e for e in filtered if e.seq < before_seq][-limit:]
    elif after_seq:
        filtered = [e for e in filtered if e.seq > after_seq][-limit:]
    else:
        filtered = filtered[-limit:]
    return filtered, latest_seq


def create_router(*, settings: Settings) -> APIRouter:
    """创建日志路由。

    Args:
        settings: 已加载的配置，用于构造鉴权依赖。

    Returns:
        含 ``GET /logs`` 的路由。
    """
    router = APIRouter(tags=["logs"])
    require_token = Depends(make_admin_token_dependency(settings))

    @router.get(
        "/logs",
        response_model=LogsResponse,
        dependencies=[require_token],
    )
    async def list_logs(
        request: Request,
        limit: int = MAX_LOG_LIMIT,
        after_seq: int = 0,
        before_seq: int | None = None,
        level: str | None = None,
        source: str | None = None,
        q: str | None = None,
    ) -> LogsResponse:
        """分页查询日志，``limit`` 必须在 1..200 之间。

        - ``after_seq``：排他向后取，用于增量轮询。
        - ``before_seq``：排他向前取，用于"加载更早"。
        - ``level`` / ``source``：精确匹配；``q``：正文关键词模糊匹配。

        优先查持久化日志库；库不可用时回退内存环形缓冲，保证面板仍可用。
        ``latest_seq`` 永远是服务端真实最新序号（不是 ``after_seq`` 回声）。
        """
        if not 1 <= limit <= MAX_LOG_LIMIT:
            raise HTTPException(
                status_code=400, detail="limit must be between 1 and 200"
            )

        store: LogStore | None = getattr(request.app.state, "log_store", None)
        if store is not None:
            try:
                result = await store.query(
                    after_seq=after_seq,
                    before_seq=before_seq,
                    limit=limit,
                    level=level,
                    source=source,
                    q=q,
                )
                return LogsResponse(
                    items=_to_items(result["items"]),
                    total=result["total"],
                    latest_seq=result["latest_seq"],
                    buffer_total=result["buffer_total"],
                )
            except LogStoreError:
                # 降级到内存查询，不向面板暴露存储故障。
                pass

        entries, latest_seq = _query_memory(
            after_seq=after_seq,
            before_seq=before_seq,
            limit=limit,
            level=level,
            source=source,
            q=q,
        )
        buffer_total = len(get_state().recent_logs(MAX_LOG_LIMIT))
        return LogsResponse(
            items=_to_items(entries),
            total=len(entries),
            latest_seq=latest_seq,
            buffer_total=buffer_total,
        )

    return router
