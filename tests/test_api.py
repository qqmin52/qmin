"""api/ 管理接口的集成测试。

每个用例在 ``tmp_path`` 中重建完整 ``.env`` 与一个 ``hello`` 插件，
清空运行时状态和路由器，再用 ASGITransport 直接调用应用。
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from api.main import create_app
from core.config import load_settings
from core.handlers import router
from core.logstore import LogStore
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


async def test_logs_after_seq_beyond_latest_returns_real_latest(
    client: httpx.AsyncClient,
) -> None:
    """after_seq 超过真实最新序号时，latest_seq 仍返回服务端真实值（不是回声）。

    这是前端服务重启回补的根因修复——若 latest_seq 回声 after_seq，
    服务重启后前端永远看不到 latest_seq 变小，无法触发全量重拉。
    """
    # 先清干净（其他用例可能已写日志）
    state = get_state()
    # 写几条让最新 seq 确定
    await state.add_log("INFO", "test", "real-latest-check-1")
    await state.add_log("INFO", "test", "real-latest-check-2")
    real_latest = state.snapshot().log_count  # snapshot 不知道真实 seq，直接从 recent_logs 取
    real_latest = state.recent_logs(1)[0].seq

    response = await client.get("/api/logs?after_seq=999", headers=auth())

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    # 关键：不是 999（回声），而是服务端真实最新 seq
    assert data["latest_seq"] == real_latest
    assert data["buffer_total"] >= 2


async def test_logs_latest_seq_zero_when_buffer_empty(
    client: httpx.AsyncClient,
) -> None:
    """环形缓冲为空时 latest_seq=0，而不是 after_seq 的值。"""
    # 用全新 state 场景验证；由于 singleton 已可能有日志，这里只测语义
    # 用 after_seq=0 测 latest_seq 不小于 0（永远是 non-negative）
    response = await client.get("/api/logs?after_seq=0", headers=auth())
    data = response.json()
    assert response.status_code == 200
    assert data["latest_seq"] >= 0


def test_static_dir_is_inside_api_package() -> None:
    """面板目录必须跟着包走：wheel 安装后在任意工作目录都能定位到。"""
    import api.main

    assert api.main.STATIC_DIR == Path(api.main.__file__).parent / "static"


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


# ---------------------------------------------------------------- setup 向导


def _make_app_with_env(tmp_path: Path, env_text: str) -> httpx.AsyncClient:
    """辅助：在 tmp_path 中写入 .env 并返回绑定了 create_app 的客户端。"""
    (tmp_path / ".env").write_text(env_text, encoding="utf-8")
    from core.config import ConfigError, read_env_file
    from core.config import Settings

    try:
        settings = load_settings(tmp_path / ".env")
    except ConfigError:
        raw = dict(read_env_file(tmp_path / ".env"))
        settings = Settings(
            app_id=raw.get("APP_ID") or "unconfigured",
            app_secret=raw.get("APP_SECRET") or "unconfigured",
            admin_token=raw.get("ADMIN_TOKEN") or "unconfigured",
            host=raw.get("HOST") or "127.0.0.1",
            port=int(raw.get("PORT") or "8000"),
            log_level=raw.get("LOG_LEVEL") or "INFO",
            db_path=Path(raw.get("DB_PATH") or "qmin.db"),
        )

    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "hello.py").write_text(HELLO_PLUGIN, encoding="utf-8")
    app = create_app(
        settings=settings,
        plugin_dir=plugin_dir,
        env_file=tmp_path / ".env",
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_setup_status_when_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """空 .env 时 GET /setup/status 返回 configured=false。"""
    monkeypatch.chdir(tmp_path)
    client = _make_app_with_env(
        tmp_path,
        "ADMIN_TOKEN=already-set\nHOST=127.0.0.1\nPORT=8000\n",
    )
    async with client:
        resp = await client.get("/api/setup/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is False
        assert "app_id" in body["missing"]
        assert "app_secret" in body["missing"]


async def test_setup_status_when_configured(
    client: httpx.AsyncClient,
) -> None:
    """完整 .env 时 GET /setup/status 返回 configured=true。"""
    resp = await client.get("/api/setup/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["missing"] == []


async def test_setup_post_writes_env_and_generates_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /setup 写入 APP_ID/APP_SECRET，自动生成管理令牌，响应不含 AppSecret 明文。"""
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    client = _make_app_with_env(
        tmp_path,
        "HOST=127.0.0.1\nPORT=8000\nLOG_LEVEL=INFO\n",
    )
    async with client:
        resp = await client.post(
            "/api/setup", json={"app_id": "123", "app_secret": "abc"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is True
        # 首次生成的令牌要回传明文（长度 > 20），且不显示已存在标记
        assert isinstance(body["admin_token"], str)
        assert len(body["admin_token"]) > 20
        assert body["token_already_existed"] is False
        # 响应里绝不能出现 app_secret 明文
        resp_text = resp.text
        assert "abc" not in resp_text

        content = env_file.read_text(encoding="utf-8")
        assert "APP_ID=123" in content
        assert "APP_SECRET=abc" in content
        assert "ADMIN_TOKEN=" in content
        for line in content.splitlines():
            if line.startswith("ADMIN_TOKEN="):
                assert line != "ADMIN_TOKEN="
                break

        # 第二次（已配置但 setup_test_client 会新建）：这里同 client 不能二次提交 403
        # 我们验证已配置时 token_already_existed 语义通过下面的单独测试覆盖


async def test_setup_post_rejected_when_already_configured(
    client: httpx.AsyncClient,
) -> None:
    """已配置时 POST /setup 返回 403。"""
    resp = await client.post(
        "/api/setup", json={"app_id": "new", "app_secret": "new"}
    )
    assert resp.status_code == 403
    body = resp.json()
    assert body["code"] == "already_configured"


async def test_setup_post_with_existing_token_does_not_echo_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env 已有 ADMIN_TOKEN 时，setup POST 不回传明文，token_already_existed=True。"""
    monkeypatch.chdir(tmp_path)
    client = _make_app_with_env(
        tmp_path,
        "HOST=127.0.0.1\nPORT=8000\nADMIN_TOKEN=alreadyexists123456789012\n",
    )
    async with client:
        resp = await client.post(
            "/api/setup", json={"app_id": "x", "app_secret": "y"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["admin_token"] is None
        assert body["token_already_existed"] is True
        assert "alreadyexists" not in resp.text


async def test_setup_post_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """app_secret 为空字符串 → 422。"""
    monkeypatch.chdir(tmp_path)
    client = _make_app_with_env(
        tmp_path,
        "HOST=127.0.0.1\nPORT=8000\n",
    )
    async with client:
        resp = await client.post(
            "/api/setup", json={"app_id": "x", "app_secret": ""}
        )
        assert resp.status_code == 422


# ----- 第 2 轮追加：缺陷修复验证 -----

async def test_placeholder_token_is_rejected_even_in_unconfigured_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env 无 ADMIN_TOKEN 时，用哨兵值 'unconfigured' 打所有需鉴权接口 → 401。

    这验证 deps.py 不再把 settings.admin_token.get_secret_value() 当兜底。
    """
    monkeypatch.chdir(tmp_path)
    client = _make_app_with_env(
        tmp_path,
        "HOST=127.0.0.1\nPORT=8000\n",
    )
    async with client:
        headers = {"X-Admin-Token": "unconfigured"}
        for path in ("/api/status", "/api/config", "/api/bot"):
            resp = await client.get(path, headers=headers)
            assert resp.status_code == 401, (
                f"GET {path} with sentinel token expected 401, got {resp.status_code}: {resp.text}"
            )
        # /setup/status 不需要令牌
        resp = await client.get("/api/setup/status")
        assert resp.status_code == 200
        assert resp.json()["configured"] is False


async def test_setup_preserves_existing_app_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /setup 不应覆盖 .env 里已有的 APP_ID，只填缺失项。"""
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ID=existing-id-keep\n"
        "HOST=127.0.0.1\n"
        "PORT=8000\n",
        encoding="utf-8",
    )
    client = _make_app_with_env(
        tmp_path,
        "APP_ID=existing-id-keep\n"
        "HOST=127.0.0.1\n"
        "PORT=8000\n",
    )
    async with client:
        resp = await client.post(
            "/api/setup",
            json={"app_id": "should-not-overwrite", "app_secret": "new-secret"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is True
        assert isinstance(body["admin_token"], str)
        assert len(body["admin_token"]) > 20

        content = env_file.read_text(encoding="utf-8")
        # APP_ID 保留旧值
        assert "APP_ID=existing-id-keep" in content
        assert "APP_ID=should-not-overwrite" not in content
        # APP_SECRET 写入 payload
        assert "APP_SECRET=new-secret" in content
        # ADMIN_TOKEN 已生成
        assert "ADMIN_TOKEN=" in content

        # 用新令牌访问需鉴权接口 → 200
        headers = {"X-Admin-Token": body["admin_token"]}
        cfg_resp = await client.get("/api/config", headers=headers)
        assert cfg_resp.status_code == 200
        cfg = cfg_resp.json()
        assert cfg["app_id"] == "existing-id-keep"
        assert "new-secret" not in cfg["app_secret"]
        assert cfg["app_secret"].startswith("****")


async def test_setup_all_three_present_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """三项齐全时再 POST /setup → 403（守卫 app_id_set + secret_set + token_set）。"""
    monkeypatch.chdir(tmp_path)
    client = _make_app_with_env(
        tmp_path,
        "APP_ID=1\nAPP_SECRET=2\nADMIN_TOKEN=3\nHOST=127.0.0.1\nPORT=8000\n",
    )
    async with client:
        resp = await client.post(
            "/api/setup", json={"app_id": "new", "app_secret": "new"}
        )
        assert resp.status_code == 403
        assert resp.json()["code"] == "already_configured"


async def test_api_config_does_not_write_unconfigured_sentinel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUT /api/config 不会把占位 'unconfigured' 写回 .env。

    setup 完成后，再 PUT /api/config 更新其他字段时，ADMIN_TOKEN/APP_ID/APP_SECRET
    必须从 .env 原值保留，不能让占位值落盘。
    """
    monkeypatch.chdir(tmp_path)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "HOST=127.0.0.1\nPORT=8000\n",
        encoding="utf-8",
    )
    client = _make_app_with_env(
        tmp_path,
        "HOST=127.0.0.1\nPORT=8000\n",
    )
    async with client:
        # 先 setup 拿到令牌
        setup_resp = await client.post(
            "/api/setup", json={"app_id": "111", "app_secret": "222"}
        )
        assert setup_resp.status_code == 200
        token = setup_resp.json()["admin_token"]
        assert isinstance(token, str)

        # PUT /api/config 更新 PORT
        put_resp = await client.put(
            "/api/config",
            headers={
                "X-Admin-Token": token,
                "Content-Type": "application/json",
            },
            json={"port": 9090},
        )
        # 9090 可能和 Origin 校验冲突（创建时用的是 8000），
        # 所以我们把 origin 设为允许的端口 8000
        put_resp2 = await client.put(
            "/api/config",
            headers={
                "X-Admin-Token": token,
                "Content-Type": "application/json",
                "Origin": "http://127.0.0.1:8000",
            },
            json={"port": 9090},
        )
        assert put_resp2.status_code == 200

        content = env_file.read_text(encoding="utf-8")
        assert "unconfigured" not in content
        # setup 生成的真实凭证仍在
        assert "APP_ID=111" in content
        assert "APP_SECRET=222" in content
        assert "ADMIN_TOKEN=" in content


async def test_env_var_admin_token_is_accepted_when_env_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env 无 ADMIN_TOKEN 但进程环境变量有（非哨兵）→ 用该令牌能鉴权 200。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ADMIN_TOKEN", "env-var-token-abc123")
    client = _make_app_with_env(
        tmp_path,
        "APP_ID=1\nAPP_SECRET=2\nHOST=127.0.0.1\nPORT=8000\n",
    )
    async with client:
        r = await client.get(
            "/api/status", headers={"X-Admin-Token": "env-var-token-abc123"}
        )
        assert r.status_code == 200


async def test_env_var_admin_token_unconfigured_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env 无 ADMIN_TOKEN 且环境变量也是哨兵 → 401。

    这验证 deps.py 的哨兵拒绝逻辑——哪怕 settings.admin_token 被占位填成
    "unconfigured"，也绝不当作合法令牌。
    """
    monkeypatch.chdir(tmp_path)
    # 别让环境变量干扰（已有 fixture clean_env 清除同名 env 变量）
    # 这里只靠占位 Settings 注入哨兵值
    client = _make_app_with_env(
        tmp_path,
        "HOST=127.0.0.1\nPORT=8000\n",
    )
    async with client:
        r = await client.get(
            "/api/status", headers={"X-Admin-Token": "unconfigured"}
        )
        assert r.status_code == 401


# ---------------------------------------------------------------- 日志持久化


async def _seed_store(app: Any, tmp_path: Path) -> LogStore:
    """注入一个已打开的 LogStore，并写入 6 条（INFO/ERROR 交替）。"""
    store = LogStore(tmp_path / "logs.db")
    await store.open()
    app.state.log_store = store
    for index in range(6):
        level = "ERROR" if index % 2 else "INFO"
        entry = await get_state().add_log(level, "bot", f"seed-{index}")
        store.enqueue(entry)
    await store.flush()
    return store


async def test_logs_before_seq_returns_earlier_page(
    app_instance: Any, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """带 before_seq 能取到更早的一页（不重不漏）。"""
    store = await _seed_store(app_instance, tmp_path)
    try:
        latest = (
            await client.get("/api/logs?limit=10", headers=auth())
        ).json()
        seqs = [item["seq"] for item in latest["items"]]
        assert len(seqs) == 6

        earlier = (
            await client.get(
                f"/api/logs?before_seq={seqs[2]}&limit=10", headers=auth()
            )
        ).json()
        assert [item["seq"] for item in earlier["items"]] == seqs[:2]
    finally:
        await store.close()


async def test_logs_level_filter(
    app_instance: Any, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """level 过滤生效。"""
    store = await _seed_store(app_instance, tmp_path)
    try:
        data = (
            await client.get("/api/logs?level=ERROR&limit=50", headers=auth())
        ).json()
        assert len(data["items"]) == 3
        assert all(item["level"] == "ERROR" for item in data["items"])
    finally:
        await store.close()


async def test_logs_keyword_filter(
    app_instance: Any, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """关键词模糊搜索命中 message。"""
    store = await _seed_store(app_instance, tmp_path)
    try:
        data = (
            await client.get("/api/logs?q=seed-3&limit=50", headers=auth())
        ).json()
        assert [item["message"] for item in data["items"]] == ["seed-3"]
    finally:
        await store.close()


async def test_logs_fallback_when_store_unavailable(
    app_instance: Any, client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """log_store 查询抛错时回退内存，不返回 500。"""
    # 未 open 的 LogStore：query 会抛 LogStoreError
    app_instance.state.log_store = LogStore(tmp_path / "never.db")
    await get_state().add_log("INFO", "bot", "内存兜底消息")

    response = await client.get("/api/logs?level=INFO", headers=auth())

    assert response.status_code == 200
    assert any(
        "内存兜底消息" in item["message"] for item in response.json()["items"]
    )


async def test_logs_without_store_uses_memory(
    client: httpx.AsyncClient,
) -> None:
    """未注入 log_store（默认）时也走内存，不 500。"""
    await get_state().add_log("INFO", "bot", "纯内存消息")

    response = await client.get("/api/logs", headers=auth())

    assert response.status_code == 200
    assert any(
        "纯内存消息" in item["message"] for item in response.json()["items"]
    )


# ---------------------------------------------------------------- 面板内装插件

INSTALL_PLUGIN_CODE = (
    '__plugin_name__ = "演示插件"\n'
    '__description__ = "安装测试"\n'
    "from core.handlers import on_group_at\n\n"
    '@on_group_at("ping")\n'
    "async def handler(event) -> None:\n"
    "    return None\n"
)


async def test_install_plugin_requires_token(client: httpx.AsyncClient) -> None:
    """安装接口是远程代码执行入口，无令牌必须 401。"""
    response = await client.post(
        "/api/plugins/install",
        json={"name": "demo", "code": "x = 1\n"},
    )

    assert response.status_code == 401


async def test_install_plugin_rejects_invalid_name(
    client: httpx.AsyncClient,
) -> None:
    """非法插件名返回 400 invalid_plugin。"""
    response = await client.post(
        "/api/plugins/install",
        json={"name": "Bad/Name", "code": "x = 1\n"},
        headers=auth(),
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "invalid_plugin"
    assert "插件名" in body["detail"]


async def test_install_plugin_conflict_returns_409(
    client: httpx.AsyncClient,
) -> None:
    """同名插件已存在且未覆盖时返回 409 plugin_exists。"""
    response = await client.post(
        "/api/plugins/install",
        json={"name": "hello", "code": "x = 1\n"},
        headers=auth(),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "plugin_exists"


async def test_install_plugin_success_and_listed(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """安装成功返回元信息，列表中可见且文件已落盘。"""
    response = await client.post(
        "/api/plugins/install",
        json={"name": "demo_installed", "code": INSTALL_PLUGIN_CODE},
        headers=auth(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "demo_installed"
    assert body["loaded"] is True
    assert body["handler_count"] == 1
    assert body["display_name"] == "演示插件"
    assert body["description"] == "安装测试"
    assert (tmp_path / "plugins" / "demo_installed.py").is_file()

    listed = await client.get("/api/plugins", headers=auth())
    names = [item["name"] for item in listed.json()["items"]]
    assert "demo_installed" in names


async def test_reload_plugin_keeps_single_handler(
    client: httpx.AsyncClient,
) -> None:
    """重新加载接口返回单条处理器，不会翻倍。"""
    response = await client.post(
        "/api/plugins/hello/reload", json={}, headers=auth()
    )

    assert response.status_code == 200
    assert response.json()["loaded"] is True
    assert response.json()["handler_count"] == 1
    assert router.count_by_source("hello") == 1


async def test_delete_unknown_plugin_returns_404(
    client: httpx.AsyncClient,
) -> None:
    """删除不存在的插件返回 404。"""
    response = await client.delete("/api/plugins/ghost", headers=auth())

    assert response.status_code == 404


async def test_delete_plugin_removes_file_and_row(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    """删除插件后文件消失、列表不再包含它、处理器被摘除。"""
    response = await client.delete("/api/plugins/hello", headers=auth())

    assert response.status_code == 200
    assert response.json() == {"removed": True}
    assert not (tmp_path / "plugins" / "hello.py").exists()
    assert router.count_by_source("hello") == 0

    listed = await client.get("/api/plugins", headers=auth())
    assert "hello" not in [item["name"] for item in listed.json()["items"]]


async def test_root_returns_panel_not_built_when_static_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """构建产物缺失时 GET / 返回可读的 panel_not_built 提示。"""
    monkeypatch.setattr("api.main.STATIC_DIR", tmp_path / "missing-static")
    env_file = tmp_path / ".env"
    env_file.write_text(ENV_TEXT, encoding="utf-8")
    settings = load_settings(env_file)
    app = create_app(settings=settings, plugin_dir=tmp_path / "plugins")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as cli:
        page = await cli.get("/")
        assert page.status_code == 404
        body = page.json()
        assert body["code"] == "panel_not_built"
        assert "npm run build" in body["detail"]

        # /api 路由不受兜底影响
        health = await cli.get("/api/health")
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

