"""首次配置向导接口（无需鉴权，用户还没有管理令牌）。

职责：
- ``GET /api/setup/status`` 返回缺失的必填键名；
- ``POST /api/setup`` 写入 APP_ID / APP_SECRET，缺失时自动生成管理令牌。

安全约束：
- 只有 APP_ID、APP_SECRET、ADMIN_TOKEN **三项齐全** 才算已配置，才拒绝重复
  提交（返回 403）；仅前两项齐全但 token 缺失时，仍允许进入并自动 generate_admin_token。
- ``POST`` 响应里 **admin_token 明文只在本次新生成时返回**；
  若 .env 原本已有 ADMIN_TOKEN，字段为 ``None`` 并置 ``token_already_existed=True``。
  这是框架唯一一次返回明文令牌的接口。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from api.schema import SetupRequest, SetupResponse, SetupStatusResponse
from core.config import (
    ConfigError,
    generate_admin_token,
    load_settings,
    read_env_file,
    write_env_file,
)

DEFAULT_ENV_FILE = Path(".env")

_REQUIRED = ("APP_ID", "APP_SECRET", "ADMIN_TOKEN")
_KEY_TO_LOWER = {
    "APP_ID": "app_id",
    "APP_SECRET": "app_secret",
    "ADMIN_TOKEN": "admin_token",
}


def _compute_missing(env_file: Path) -> list[str]:
    values = dict(read_env_file(env_file))
    return [
        _KEY_TO_LOWER[key]
        for key in _REQUIRED
        if not values.get(key, "").strip()
    ]


def create_router(env_file: Path = DEFAULT_ENV_FILE) -> APIRouter:
    router = APIRouter(prefix="/setup", tags=["setup"])

    @router.get("/status", response_model=SetupStatusResponse)
    async def setup_status(_request: Request) -> SetupStatusResponse:
        missing = _compute_missing(env_file)
        return SetupStatusResponse(
            configured=len(missing) == 0, missing=missing
        )

    @router.post("", response_model=SetupResponse)
    async def setup(
        payload: SetupRequest, request: Request
    ) -> SetupResponse | JSONResponse:
        existing = dict(read_env_file(env_file))
        app_id_set = bool(existing.get("APP_ID", "").strip())
        secret_set = bool(existing.get("APP_SECRET", "").strip())
        token_set = bool(existing.get("ADMIN_TOKEN", "").strip())

        # 守卫：三项齐全才算已配置，才拒绝重复提交。
        # 只有 APP_ID/APP_SECRET 齐全但 token 缺失 → 仍然允许进入，本次会自动 generate_admin_token。
        if app_id_set and secret_set and token_set:
            return JSONResponse(
                status_code=403,
                content={
                    "code": "already_configured",
                    "detail": "已配置，无需重复提交",
                },
            )

        # 记录本次 generate_admin_token 调用前 ADMIN_TOKEN 是否已存在——
        # 若原本不存在，则说明本次 setup POST 就是令牌的首次生成点，
        # 理应把明文回传一次（这是框架唯一一次返回明文令牌的接口）。
        had_admin_token_before = token_set

        values = dict(existing)
        # 只在对应键为空时写入，避免用户误把已有 AppID / Secret 改掉。
        if not app_id_set:
            values["APP_ID"] = payload.app_id.strip()
        if not secret_set:
            values["APP_SECRET"] = payload.app_secret.strip()

        # 缺令牌时调用 generate_admin_token（纯原子写、不打印、不记 RuntimeState）
        admin_token_plain: str | None = None
        if not token_set:
            admin_token_plain = generate_admin_token(env_file)
            values["ADMIN_TOKEN"] = admin_token_plain

        write_env_file(env_file, values)

        # 刷新 app.state.settings（ConfigError 也接受——说明还没配全，不要抛）。
        try:
            request.app.state.settings = load_settings(env_file)
        except ConfigError:
            pass

        # 只有本次新生成的令牌才回传明文
        token_to_echo = admin_token_plain if not had_admin_token_before else None

        return SetupResponse(
            configured=True,
            admin_token=token_to_echo,
            token_already_existed=had_admin_token_before,
            restart_required=False,
        )

    return router
