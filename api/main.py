"""FastAPI 应用工厂。

模块级不创建 app 实例：``settings`` 需要先加载，鉴权依赖依赖它。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes import config as config_routes
from api.routes import logs as logs_routes
from api.routes import plugins as plugins_routes
from api.routes import status as status_routes
from core.config import Settings

# 前端构建产物目录；不存在时不挂载。
STATIC_DIR = Path("api/static")


def create_app(*, settings: Settings, plugin_dir: Path) -> FastAPI:
    """创建管理接口应用。

    Args:
        settings: 已加载的配置，用于鉴权、脱敏读取与 Origin 校验。
        plugin_dir: 插件目录，插件启停时从这里重新加载。

    Returns:
        挂载了 ``/api`` 下全部路由的 FastAPI 实例。
    """
    app = FastAPI(title="Qmin 管理接口", version="0.1.0")
    app.state.settings = settings
    app.state.plugin_dir = plugin_dir

    app.include_router(
        status_routes.create_router(settings=settings), prefix="/api"
    )
    app.include_router(
        plugins_routes.create_router(settings=settings, plugin_dir=plugin_dir),
        prefix="/api",
    )
    app.include_router(logs_routes.create_router(settings=settings), prefix="/api")
    app.include_router(
        config_routes.create_router(settings=settings), prefix="/api"
    )

    @app.exception_handler(KeyError)
    async def _handle_key_error(_request: Request, exc: KeyError) -> JSONResponse:
        """把缺失资源映射为 404。"""
        detail = exc.args[0] if exc.args else "not found"
        return JSONResponse(
            status_code=404, content={"code": "not_found", "detail": str(detail)}
        )

    @app.exception_handler(ValueError)
    async def _handle_value_error(
        _request: Request, exc: ValueError
    ) -> JSONResponse:
        """把非法取值映射为 400。"""
        return JSONResponse(
            status_code=400, content={"code": "invalid_request", "detail": str(exc)}
        )

    # 静态面板必须在所有 /api 路由之后挂载，避免抢占接口路径。
    if STATIC_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="webui")

    return app
