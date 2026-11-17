"""FastAPI 应用工厂。

模块级不创建 app 实例：``settings`` 需要先加载，鉴权依赖依赖它。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.bot_manager import BotManager
from api.routes import bot as bot_routes
from api.routes import config as config_routes
from api.routes import logs as logs_routes
from api.routes import plugins as plugins_routes
from api.routes import setup as setup_routes
from api.routes import status as status_routes
from core.config import Settings
from core.logstore import LogStore, LogStoreError
from core.state import get_state

# 前端构建产物目录；不存在时不挂载。
STATIC_DIR = Path("api/static")


def create_app(
    *,
    settings: Settings,
    plugin_dir: Path,
    env_file: Path = Path(".env"),
    bot_manager: BotManager | None = None,
    log_store: LogStore | None = None,
    auto_start_bot: bool = False,
) -> FastAPI:
    """创建管理接口应用。

    Args:
        settings: 已加载的配置，用于鉴权、脱敏读取与 Origin 校验。
        plugin_dir: 插件目录，插件启停时从这里重新加载。
        env_file: ``.env`` 文件路径，配置向导读写都基于此。
        bot_manager: ``qmin start`` 会始终注入，供面板手动启停与自动连接。
        log_store: 日志持久化存储；为 None 时日志接口回退到内存环形缓冲。
        auto_start_bot: 启动时是否自动连接机器人（有完整配置时为 True）。

    Returns:
        挂载了 ``/api`` 下全部路由的 FastAPI 实例。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """启动时接上日志落盘并按需连机器人，关闭时先停机器人再写干净队列。"""
        # 从 app.state 读取，允许调用方在 create_app 之后再注入 log_store。
        store = getattr(app.state, "log_store", None)
        if store is not None:
            try:
                await store.open()
                get_state().set_sink(store.enqueue)
                asyncio.create_task(store.run())
            except LogStoreError:
                # 落库失败必须降级到内存，不能拖垮面板。
                get_state().set_sink(None)

        manager = getattr(app.state, "bot_manager", None)
        if auto_start_bot and manager is not None:
            # 不 await：连接握手可能耗时数秒，不能阻塞面板启动。
            asyncio.create_task(manager.start())

        yield

        # 先停机器人再关日志，否则「机器人已停止」这条日志落不了库。
        if auto_start_bot and manager is not None:
            try:
                await manager.stop()
            except Exception:
                pass
        get_state().set_sink(None)
        store = getattr(app.state, "log_store", None)
        if store is not None:
            try:
                await store.close()
            except Exception:
                pass

    app = FastAPI(title="Qmin 管理接口", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.plugin_dir = plugin_dir
    app.state.env_file = env_file
    app.state.bot_manager = bot_manager
    app.state.log_store = log_store

    app.include_router(setup_routes.create_router(env_file=env_file), prefix="/api")
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
    app.include_router(
        bot_routes.create_router(settings=settings), prefix="/api"
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
    else:
        # 面板产物缺失时给出可读提示，避免新用户 clone 后只看到裸 404。
        @app.get("/", include_in_schema=False)
        async def panel_not_built() -> JSONResponse:
            return JSONResponse(
                status_code=404,
                content={
                    "code": "panel_not_built",
                    "detail": "管理面板未构建，请执行：cd webui && npm install && npm run build",
                },
            )

    return app
