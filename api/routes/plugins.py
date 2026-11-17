"""插件列表与启停接口。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from api.deps import (
    make_admin_token_dependency,
    make_origin_dependency,
    require_json_content_type,
)
from api.schema import (
    InstallPluginRequest,
    PluginInfo,
    PluginListResponse,
    RemovePluginResponse,
    TogglePluginRequest,
)
from core.config import Settings
from core.plugins import (
    PluginExistsError,
    PluginValidationError,
    install_plugin,
    reload_plugin,
    remove_plugin,
    set_plugin_enabled,
)
from core.state import PluginRecord, get_state


def _to_info(record: PluginRecord) -> PluginInfo:
    """把内部插件记录转换为对外模型。"""
    return PluginInfo(
        name=record.name,
        enabled=record.enabled,
        loaded=record.loaded,
        handler_count=record.handler_count,
        error=record.error,
        display_name=record.display_name,
        description=record.description,
        version=record.version,
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

    @router.post(
        "/install",
        response_model=PluginInfo,
        dependencies=[
            require_token,
            Depends(require_json_content_type),
            require_origin,
        ],
    )
    async def install(payload: InstallPluginRequest) -> PluginInfo | JSONResponse:
        """安装或覆盖插件：校验 → 原子写 → 立即加载（远程代码执行入口）。"""
        try:
            record = await install_plugin(
                payload.name,
                payload.code,
                plugin_dir=plugin_dir,
                overwrite=payload.overwrite,
            )
        except PluginValidationError as exc:
            return JSONResponse(
                status_code=400,
                content={"code": "invalid_plugin", "detail": str(exc)},
            )
        except PluginExistsError:
            return JSONResponse(
                status_code=409,
                content={
                    "code": "plugin_exists",
                    "detail": f"插件已存在：{payload.name}",
                },
            )
        return _to_info(record)

    @router.post(
        "/{name}/reload",
        response_model=PluginInfo,
        dependencies=[
            require_token,
            Depends(require_json_content_type),
            require_origin,
        ],
    )
    async def reload(name: str) -> PluginInfo:
        """重新加载磁盘上的插件文件；文件不存在时由全局处理器映射为 404。"""
        return _to_info(await reload_plugin(name, plugin_dir=plugin_dir))

    @router.delete(
        "/{name}",
        response_model=RemovePluginResponse,
        dependencies=[require_token, require_origin],
    )
    async def remove(name: str) -> RemovePluginResponse:
        """删除插件文件并摘除处理器；不存在时映射为 404。"""
        await remove_plugin(name, plugin_dir=plugin_dir)
        return RemovePluginResponse(removed=True)

    return router
