"""api/ 管理接口的集成测试。

每个用例在 ``tmp_path`` 中重建完整 ``.env`` 与一个 ``hello`` 插件，
清空运行时状态和路由器，再用 ASGITransport 直接调用应用。
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from api.main import create_app
from core.config import load_settings
from core.handlers import router
from core.plugins import load_plugins
from core.state import StatusSnapshot, get_state, reset_state

ADMIN_TOKEN = "test-admin-token-123456"
APP_SECRET = "super-secret-value-123456"

ENV_TEXT = (
    "APP_ID=102345678\n"
    f"APP_SECRET={APP_SECRET}\n"
    f"ADMIN_TOKEN={ADMIN_TOKEN}\n"
    "HOST=127.0.0.1\n"
    "PORT=8000\n"
    "LOG_LEVEL=INFO\n"
    "DB_PATH=qmin.db\n"
)

HELLO_PLUGIN = '''"""测试插件：注册一个群 @ 处理器。"""

from core.handlers import on_group_at


@on_group_at("你好")
async def hello(event) -> None:
    await event.reply("你好呀")
'''


def auth() -> dict[str, str]:
    """返回带正确管理令牌的请求头。"""
    return {"X-Admin-Token": ADMIN_TOKEN}


@pytest.fixture(autouse=True)
async def app_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[object]:
    """准备临时工作目录、配置与插件，并创建应用。"""
    reset_state()
    router.clear()
    monkeypatch.chdir(tmp_path)

    (tmp_path / ".env").write_text(ENV_TEXT, encoding="utf-8")
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    (plugin_dir / "hello.py").write_text(HELLO_PLUGIN, encoding="utf-8")

    await load_plugins(plugin_dir)
    settings = load_settings(tmp_path / ".env")
    app = create_app(settings=settings, plugin_dir=plugin_dir)
    yield app

    reset_state()
    router.clear()


@pytest.fixture
async def client(app_instance: object) -> AsyncIterator[httpx.AsyncClient]:
    """基于 ASGITransport 的异步客户端（不监听端口）。"""
    transport = httpx.ASGITransport(app=app_instance)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1:8000"
    ) as async_client:
        yield async_client


async def test_health_needs_no_token(client: httpx.AsyncClient) -> None:
    """探活接口无需令牌。"""
    response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_status_requires_valid_token(client: httpx.AsyncClient) -> None:
    """状态接口在缺失 / 错误令牌时 401，正确令牌返回与快照一致的字段。"""
    assert (await client.get("/api/status")).status_code == 401
    assert (
        await client.get("/api/status", headers={"X-Admin-Token": "wrong"})
    ).status_code == 401

    response = await client.get("/api/status", headers=auth())

    assert response.status_code == 200
    expected_keys = {field.name for field in dataclasses.fields(StatusSnapshot)}
    assert set(response.json()) == expected_keys


async def test_toggle_plugin_removes_and_restores_handlers(
    client: httpx.AsyncClient,
) -> None:
    """禁用插件会摘除处理器，重新启用后恢复。"""
    listed = await client.get("/api/plugins", headers=auth())
    assert listed.status_code == 200
    names = [item["name"] for item in listed.json()["items"]]
    assert "hello" in names

    disabled = await client.post(
        "/api/plugins/hello/toggle", json={"enabled": False}, headers=auth()
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled.json()["loaded"] is False
    assert disabled.json()["handler_count"] == 0
    assert router.count_by_source("hello") == 0

    listed = await client.get("/api/plugins", headers=auth())
    hello = next(
        item for item in listed.json()["items"] if item["name"] == "hello"
    )
    assert hello["enabled"] is False

    enabled = await client.post(
        "/api/plugins/hello/toggle", json={"enabled": True}, headers=auth()
    )
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True
    assert router.count_by_source("hello") == 1


async def test_toggle_unknown_plugin_returns_404(
    client: httpx.AsyncClient,
) -> None:
    """未知插件返回 404。"""
    response = await client.post(
        "/api/plugins/missing/toggle", json={"enabled": True}, headers=auth()
    )

    assert response.status_code == 404


async def test_logs_limit_bounds(client: httpx.AsyncClient) -> None:
    """limit 越界返回 400，合法值按条数截断。"""
    state = get_state()
    for index in range(8):
        await state.add_log("INFO", "test", f"log-{index}")

    assert (
        await client.get("/api/logs?limit=0", headers=auth())
    ).status_code == 400
    assert (
        await client.get("/api/logs?limit=201", headers=auth())
    ).status_code == 400

    response = await client.get("/api/logs?limit=5", headers=auth())
    assert response.status_code == 200
    assert response.json()["total"] == 5
    assert len(response.json()["items"]) <= 5


async def test_config_get_never_leaks_secrets(
    client: httpx.AsyncClient,
) -> None:
    """配置读取只返回打码值，响应体不含任何明文密钥。"""
    response = await client.get("/api/config", headers=auth())

    assert response.status_code == 200
    body = response.text
    assert APP_SECRET not in body
    assert ADMIN_TOKEN not in body

    data = response.json()
    assert data["app_id"] == "102345678"
    assert data["app_secret"] != APP_SECRET
    assert data["admin_token_set"] is True
    assert "db_path" in data


async def test_put_config_validates_and_writes_env(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """非 JSON 415、跨域 403；正常请求写回 .env 且不回显密钥。"""
    url = "/api/config"

    bad_type = await client.put(
        url,
        content="APP_ID=1",
        headers={**auth(), "Content-Type": "text/plain"},
    )
    assert bad_type.status_code == 415

    bad_origin = await client.put(
        url,
        json={"app_id": "1"},
        headers={**auth(), "Origin": "http://evil.example"},
    )
    assert bad_origin.status_code == 403

    response = await client.put(
        url,
        json={"app_id": "999888777", "app_secret": "new-secret-value-xyz"},
        headers=auth(),
    )
    assert response.status_code == 200
    assert response.json() == {"saved": True, "restart_required": True}
    assert "new-secret-value-xyz" not in response.text

    content = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "APP_ID=999888777" in content
    assert "APP_SECRET=new-secret-value-xyz" in content

    settings = load_settings(tmp_path / ".env")
    assert settings.app_id == "999888777"
    assert settings.admin_token.get_secret_value() == ADMIN_TOKEN


async def test_put_config_keeps_unknown_keys_and_rejects_invalid(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """未知键保留；非法 port / 空 app_id 返回 422。"""
    env_file = tmp_path / ".env"
    env_file.write_text(
        env_file.read_text(encoding="utf-8") + "FOO=bar\n", encoding="utf-8"
    )

    too_large_port = await client.put(
        "/api/config", json={"port": 70000}, headers=auth()
    )
    assert too_large_port.status_code == 422

    empty_app_id = await client.put(
        "/api/config", json={"app_id": ""}, headers=auth()
    )
    assert empty_app_id.status_code == 422

    response = await client.put(
        "/api/config", json={"log_level": "DEBUG"}, headers=auth()
    )
    assert response.status_code == 200

    content = env_file.read_text(encoding="utf-8")
    assert "FOO=bar" in content
    assert "LOG_LEVEL=DEBUG" in content
    assert f"APP_SECRET={APP_SECRET}" in content


async def test_logs_after_seq_returns_only_newer(
    client: httpx.AsyncClient,
) -> None:
    """after_seq 只返回序号更大的日志。"""
    state = get_state()
    for index in range(5):
        await state.add_log("INFO", "test", f"log-{index}")

    response = await client.get("/api/logs?after_seq=2", headers=auth())

    assert response.status_code == 200
    data = response.json()
    assert [item["seq"] for item in data["items"]] == [3, 4, 5]
    assert data["latest_seq"] == 5


async def test_logs_after_seq_empty_returns_after_seq(
    client: httpx.AsyncClient,
) -> None:
    """没有新日志时 latest_seq 回落到 after_seq。"""
    response = await client.get("/api/logs?after_seq=7", headers=auth())

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["latest_seq"] == 7


async def test_static_panel_is_served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """静态面板挂载在 /，且不会吞掉 /api 路由。"""
    static_dir = tmp_path / "api" / "static"
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text(
        "<!DOCTYPE html><html><body>Qmin static panel</body></html>",
        encoding="utf-8",
    )
    monkeypatch.setattr("api.main.STATIC_DIR", static_dir)

    env_file = tmp_path / ".env"
    env_file.write_text(ENV_TEXT, encoding="utf-8")
    settings = load_settings(env_file)
    app = create_app(settings=settings, plugin_dir=tmp_path / "plugins")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/")
        assert page.status_code == 200
        assert "Qmin static panel" in page.text

        health = await client.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}
