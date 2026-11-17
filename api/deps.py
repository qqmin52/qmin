"""管理接口的 FastAPI 依赖：令牌、Content-Type 与 Origin 校验。

- 依赖敏感的配置（管理令牌、端口）一律通过闭包注入，不使用模块级可变状态。
- 管理令牌校验每次从 ``env_file`` 读取，保证 setup POST 写新 token 后立刻生效。
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from pathlib import Path

from fastapi import Header, HTTPException, Request

from core.config import Settings, UNCONFIGURED_TOKEN, read_env_file


def make_admin_token_dependency(settings: Settings) -> Callable[..., None]:
    """构造校验 ``X-Admin-Token`` 的依赖。

    每次请求先读 ``request.app.state.env_file`` 里的 ADMIN_TOKEN，
    找不到再回退到进程环境变量（即 settings 里加载的）。
    哨兵值 ``UNCONFIGURED_TOKEN``（qmin api 占位模式的 Settings 默认值）
    永不被视为合法令牌——.env 与环境变量都缺失时直接 401。

    Args:
        settings: 已加载的配置；仅作为环境变量的回退来源。

    Returns:
        无返回值的依赖函数；令牌缺失或与配置不一致时抛 401。
    """

    def require_admin_token(
        request: Request,
        x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    ) -> None:
        """校验请求头中的管理令牌。"""
        env_file: Path = getattr(request.app.state, "env_file", Path(".env"))
        latest = dict(read_env_file(env_file)).get("ADMIN_TOKEN", "").strip()
        if not latest:
            # .env 无令牌 → 回退到 settings（进程环境变量），但拒绝哨兵值。
            fallback = settings.admin_token.get_secret_value().strip()
            if fallback and fallback != UNCONFIGURED_TOKEN:
                latest = fallback
        if not latest:
            raise HTTPException(
                status_code=401, detail="admin token not configured"
            )
        provided = x_admin_token or ""
        if not secrets.compare_digest(
            provided.encode("utf-8"), latest.encode("utf-8")
        ):
            raise HTTPException(status_code=401, detail="invalid admin token")

    return require_admin_token


def require_json_content_type(
    content_type: str | None = Header(default=None),
) -> None:
    """要求请求体为 JSON。

    Args:
        content_type: 请求的 ``Content-Type`` 头。

    Raises:
        HTTPException: 缺失或不是 ``application/json`` 时返回 415。
    """
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type != "application/json":
        raise HTTPException(
            status_code=415, detail="content-type must be application/json"
        )


def make_origin_dependency(settings: Settings) -> Callable[..., None]:
    """构造 Origin 校验依赖，仅允许本机管理面板来源。

    Args:
        settings: 已加载的配置，端口从这里取。

    Returns:
        无返回值的依赖函数；缺少 Origin 头时放行（非浏览器请求）。
    """
    allowed = {
        f"http://127.0.0.1:{settings.port}",
        f"http://localhost:{settings.port}",
    }

    def check_origin(origin: str | None = Header(default=None)) -> None:
        """校验跨域来源。"""
        if origin is None:
            return
        if origin not in allowed:
            raise HTTPException(status_code=403, detail="origin not allowed")

    return check_origin
