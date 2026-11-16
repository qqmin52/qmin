"""插件列表与启停接口。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from api.deps import (
    make_admin_token_dependency,
    make_origin_dependency,
    require_json_content_type,
)
from api.schema import PluginInfo, PluginListResponse, TogglePluginRequest
from core.config import Settings
from core.plugins import set_plugin_enabled
from core.state import PluginRecord, get_state


def _to_info(record: PluginRecord) -> PluginInfo:
    """把内部插件记录转换为对外模型。"""
    return PluginInfo(
        name=record.name,
        enabled=record.enabled,
        loaded=record.loaded,
        handler_count=record.handler_count,
        error=record.error,
    )


def create_router(*, settings: Settings, plugin_dir: Path) -> APIRouter:
    """创建插件路由。

    Args:
        settings: 已加载的配置，用于构造鉴权与 Origin 依赖。
        plugin_dir: 插件目录，启用插件时从这里重新加载。

    Returns:
        含插件列表与启停接口的路由。
    """
    router = APIRouter(prefix="/plugins", tags=["plugins"])
    require_token = Depends(make_admin_token_dependency(settings))
    require_origin = Depends(make_origin_dependency(settings))

    @router.get(
        "",
        response_model=PluginListResponse,
        dependencies=[require_token],
    )
    async def list_plugins() -> PluginListResponse:
        """返回全部已发现插件。"""
        items = [_to_info(record) for record in get_state().list_plugins()]
        return PluginListResponse(items=items, total=len(items))

    @router.post(
        "/{name}/toggle",
        response_model=PluginInfo,
        dependencies=[
            require_token,
            Depends(require_json_content_type),
            require_origin,
        ],
    )
    async def toggle_plugin(name: str, payload: TogglePluginRequest) -> PluginInfo:
        """启用或禁用插件，并同步注册 / 摘除其处理器。"""
        record = await set_plugin_enabled(
            name, payload.enabled, plugin_dir=plugin_dir
        )
        return _to_info(record)

    return router
