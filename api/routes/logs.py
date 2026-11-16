"""运行日志接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.deps import make_admin_token_dependency
from api.schema import LogItem, LogsResponse
from core.config import Settings
from core.state import get_state

# 单次最多返回的日志条数，与环形缓冲容量一致。
MAX_LOG_LIMIT: int = 200


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
    async def list_logs(limit: int = MAX_LOG_LIMIT, after_seq: int = 0) -> LogsResponse:
        """返回最近日志，``limit`` 必须在 1..200 之间。

        ``after_seq`` 用于增量轮询：只返回 ``seq`` 大于它的日志。
        """
        if not 1 <= limit <= MAX_LOG_LIMIT:
            raise HTTPException(
                status_code=400, detail="limit must be between 1 and 200"
            )

        entries = [
            entry
            for entry in get_state().recent_logs(MAX_LOG_LIMIT)
            if entry.seq > after_seq
        ][-limit:]
        items = [
            LogItem(
                seq=entry.seq,
                time=entry.time,
                level=entry.level,
                source=entry.source,
                message=entry.message,
            )
            for entry in entries
        ]
        return LogsResponse(
            items=items,
            total=len(items),
            latest_seq=entries[-1].seq if entries else after_seq,
        )

    return router
