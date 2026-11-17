"""Bot 手动启停接口（需鉴权）。

仅在 ``qmin api`` 模式下由面板手动控制；``qmin run`` 模式下由 CLI 自行管理，
此时 bot_manager 为 None，返回 409 告知当前模式不支持。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from api.bot_manager import BotManager
from api.deps import make_admin_token_dependency
from api.schema import BotActionResult, BotStatusResponse
from core.config import Settings


def create_router(*, settings: Settings) -> APIRouter:
    """创建 bot 路由。

    Args:
        settings: 用于构造 admin_token 鉴权依赖。

    Returns:
        含 ``GET /bot``、``POST /bot/start``、``POST /bot/stop`` 的路由。
    """
    router = APIRouter(prefix="/bot", tags=["bot"])
    require_token = Depends(make_admin_token_dependency(settings))

    def _get_manager(request: Request) -> BotManager | None:
        return getattr(request.app.state, "bot_manager", None)

    @router.get("", response_model=BotStatusResponse, dependencies=[require_token])
    async def bot_status(request: Request) -> BotStatusResponse:
        manager = _get_manager(request)
        if manager is None:
            return JSONResponse(
                status_code=409,
                content={"detail": "当前模式不支持手动启停"},
            )
        return BotStatusResponse(running=manager.running)

    @router.post(
        "/start", response_model=BotActionResult, dependencies=[require_token]
    )
    async def bot_start(request: Request) -> BotActionResult | JSONResponse:
        manager = _get_manager(request)
        if manager is None:
            return JSONResponse(
                status_code=409,
                content={"detail": "当前模式不支持手动启停"},
            )
        result = await manager.start()
        return BotActionResult(started=result["started"], error=result["error"])

    @router.post(
        "/stop", response_model=BotActionResult, dependencies=[require_token]
    )
    async def bot_stop(request: Request) -> BotActionResult | JSONResponse:
        manager = _get_manager(request)
        if manager is None:
            return JSONResponse(
                status_code=409,
                content={"detail": "当前模式不支持手动启停"},
            )
        result = await manager.stop()
        return BotActionResult(started=result["started"], error=result["error"])

    return router
