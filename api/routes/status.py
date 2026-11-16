"""状态与探活接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from api.deps import make_admin_token_dependency
from api.schema import HealthResponse, StatusResponse
from core.config import Settings
from core.state import get_state


def create_router(*, settings: Settings) -> APIRouter:
    """创建状态路由。

    Args:
        settings: 已加载的配置，用于构造鉴权依赖。

    Returns:
        含 ``/health`` 与 ``/status`` 的路由。
    """
    router = APIRouter(tags=["status"])
    require_token = Depends(make_admin_token_dependency(settings))

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """探活接口，不需要令牌。"""
        return HealthResponse(status="ok")

    @router.get(
        "/status",
        response_model=StatusResponse,
        dependencies=[require_token],
    )
    async def read_status() -> StatusResponse:
        """返回运行时状态快照。"""
        snapshot = get_state().snapshot()
        return StatusResponse(
            connected=snapshot.connected,
            started_at=snapshot.started_at,
            uptime_seconds=snapshot.uptime_seconds,
            plugin_total=snapshot.plugin_total,
            plugin_enabled=snapshot.plugin_enabled,
            plugin_loaded=snapshot.plugin_loaded,
            log_count=snapshot.log_count,
        )

    return router
