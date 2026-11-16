"""配置读取与更新接口。

读取永远脱敏；更新会全量重写 ``.env``，且要求重启后生效。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends

from api.deps import (
    make_admin_token_dependency,
    make_origin_dependency,
    require_json_content_type,
)
from api.schema import ConfigOut, ConfigUpdateRequest
from core.config import Settings, read_env_file, write_env_file

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
        settings: 已加载的配置；读取与合并都以它为基线。
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
    async def read_config() -> ConfigOut:
        """返回脱敏后的配置。"""
        return ConfigOut(**settings.to_public_dict())

    @router.put(
        "",
        dependencies=[
            require_token,
            Depends(require_json_content_type),
            require_origin,
        ],
    )
    async def update_config(payload: ConfigUpdateRequest) -> dict[str, bool]:
        """合并更新 ``.env``，不热重载当前进程配置。

        以现有 ``.env`` 为基线：payload 中为 ``None`` 的字段不覆盖，
        未知键原样保留；管理令牌始终保留原值（缺失时用当前配置补齐）。
        """
        values = dict(read_env_file(env_file))
        for field, value in payload.model_dump(exclude_none=True).items():
            values[_FIELD_TO_ENV[field]] = str(value)

        values.setdefault("ADMIN_TOKEN", settings.admin_token.get_secret_value())
        values.setdefault("APP_ID", settings.app_id)
        values.setdefault("APP_SECRET", settings.app_secret.get_secret_value())

        write_env_file(env_file, values)
        return {"saved": True, "restart_required": True}

    return router
