"""配置读取与更新接口。

读取永远脱敏；更新会全量重写 ``.env``，且要求重启后生效。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request

from api.deps import (
    make_admin_token_dependency,
    make_origin_dependency,
    require_json_content_type,
)
from api.schema import ConfigOut, ConfigUpdateRequest
from core.config import ConfigError, Settings, load_settings, read_env_file, write_env_file

DEFAULT_ENV_FILE = Path(".env")

# 请求字段到 ``.env`` 变量名的映射（仅这些字段可更新）。
_FIELD_TO_ENV: dict[str, str] = {
    "app_id": "APP_ID",
    "app_secret": "APP_SECRET",
    "host": "HOST",
    "port": "PORT",
    "log_level": "LOG_LEVEL",
    "db_path": "DB_PATH",
}


def create_router(
    *, settings: Settings, env_file: Path = DEFAULT_ENV_FILE
) -> APIRouter:
    """创建配置路由。

    Args:
        settings: 已加载的配置（用于构造令牌 / Origin 校验依赖；路由函数体
            不再直接引用 settings，每次都从 ``request.app.state.settings`` 取最新）。
        env_file: ``.env`` 路径，更新时写回这里。

    Returns:
        含 ``GET /config`` 与 ``PUT /config`` 的路由。
    """
    router = APIRouter(prefix="/config", tags=["config"])
    require_token = Depends(make_admin_token_dependency(settings))
    require_origin = Depends(make_origin_dependency(settings))

    @router.get(
        "",
        response_model=ConfigOut,
        dependencies=[require_token],
    )
    async def read_config(request: Request) -> ConfigOut:
        """返回脱敏后的配置。基线是最近一次 load_settings 的结果（setup / put 后会刷新）。"""
        live: Settings = getattr(request.app.state, "settings", settings)
        return ConfigOut(**live.to_public_dict())

    @router.put(
        "",
        dependencies=[
            require_token,
            Depends(require_json_content_type),
            require_origin,
        ],
    )
    async def update_config(
        payload: ConfigUpdateRequest, request: Request
    ) -> dict[str, bool]:
        """合并更新 ``.env``，不热重载当前进程配置。

        以现有 ``.env`` 为基线：payload 中为 ``None`` 的字段不覆盖，
        未知键原样保留；ADMIN_TOKEN 始终保留 .env 原值（绝不从占位 settings 兜底）。
        """
        values = dict(read_env_file(env_file))
        for field, value in payload.model_dump(exclude_none=True).items():
            values[_FIELD_TO_ENV[field]] = str(value)

        # ADMIN_TOKEN、APP_ID、APP_SECRET 都只保留 .env 原值；占位 settings
        # （如 "unconfigured"）禁止写入 .env。
        values.setdefault("ADMIN_TOKEN", "")
        values.setdefault("APP_ID", "")
        values.setdefault("APP_SECRET", "")

        write_env_file(env_file, values)

        # 与 setup 一致：刷新 app.state.settings，让随后 GET /config 读最新值。
        try:
            request.app.state.settings = load_settings(env_file)
        except ConfigError:
            pass

        return {"saved": True, "restart_required": True}

    return router
