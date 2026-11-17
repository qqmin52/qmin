"""api/bot_manager.py 的测试。

用 FakeBot 替换 QminBot，验证 BotManager 的状态机：
- start 立即抛异常 → 返回 started=False + error（done callback 静默）
- start 正常返回（立即结束，不阻塞）→ started=True
- start 挂起直到窗口后抛 → start 返回 started=True，done callback 写"异常退出"
- 重复 start 幂等（已有 task 直接返回）
- stop 后 running 为 False
- 每次 start 都从 .env load_settings → 运行时改凭证立即生效
- .env 缺凭证时 start 返回 started=False，不构造 QminBot
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from api.bot_manager import BotManager
from core.state import RuntimeState


# ---------- FakeBot ----------
class _SuccessBot:
    """start 立即完成（正常退出）。"""

    instances: list["_SuccessBot"] = []

    def __init__(self, *, app_id: str, app_secret: str, state: object) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        _SuccessBot.instances.append(self)

    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return


class _ErrorBot:
    """start 立即抛 RuntimeError。"""

    instances: list["_ErrorBot"] = []

    def __init__(self, *, app_id: str, app_secret: str, state: object) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        _ErrorBot.instances.append(self)

    async def start(self) -> None:
        raise RuntimeError("nope")

    async def stop(self) -> None:
        return


class _SlowBot:
    """start 挂起，用于测重复 start 幂等。"""

    instances: list["_SlowBot"] = []

    def __init__(self, *, app_id: str, app_secret: str, state: object) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        _SlowBot.instances.append(self)
        self.started = asyncio.Event()

    async def start(self) -> None:
        self.started.set()
        await asyncio.Event().wait()  # 永久挂起

    async def stop(self) -> None:
        return


# ---------- 辅助 ----------
def _write_valid_env(tmp_path: Path) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ID=id-1\nAPP_SECRET=secret-1\n"
        "ADMIN_TOKEN=toxxxxxxkenneth\n"
        "HOST=127.0.0.1\nPORT=8000\n",
        encoding="utf-8",
    )
    return env_file


def _write_invalid_env(tmp_path: Path) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "HOST=127.0.0.1\nPORT=8000\n",
        encoding="utf-8",
    )
    return env_file


# ---------- 单元 ----------
async def test_start_succeeds_and_running_is_true(tmp_path: Path) -> None:
    state = RuntimeState()
    env_file = _write_valid_env(tmp_path)
    with patch("api.bot_manager.QminBot", _SuccessBot):
        manager = BotManager(env_file=env_file, state=state)
        result = await manager.start()
        assert result == {"started": True, "error": None}
        await asyncio.sleep(0)
        assert manager.running is False


async def test_start_failure_returns_error_and_logs(tmp_path: Path) -> None:
    state = RuntimeState()
    env_file = _write_valid_env(tmp_path)
    with patch("api.bot_manager.QminBot", _ErrorBot):
        manager = BotManager(env_file=env_file, state=state)
        result = await manager.start()
        assert result["started"] is False
        assert "RuntimeError" in str(result["error"])
        assert "nope" in str(result["error"])
        assert manager.running is False
        snapshot = state.snapshot()
        assert snapshot.log_count == 1
        msg = state.recent_logs()[0].message
        assert "启动失败" in msg
        assert "异常退出" not in msg


async def test_repeated_start_is_idempotent(tmp_path: Path) -> None:
    state = RuntimeState()
    env_file = _write_valid_env(tmp_path)
    with patch("api.bot_manager.QminBot", _SlowBot):
        manager = BotManager(env_file=env_file, state=state)
        _SlowBot.instances.clear()
        await manager.start()
        assert manager.running is True
        result2 = await manager.start()
        assert result2 == {"started": True, "error": None}
        assert len(_SlowBot.instances) == 1
        await manager.stop()


async def test_stop_when_not_running_returns_success(tmp_path: Path) -> None:
    state = RuntimeState()
    env_file = _write_valid_env(tmp_path)
    with patch("api.bot_manager.QminBot", _SuccessBot):
        manager = BotManager(env_file=env_file, state=state)
        result = await manager.stop()
        assert result == {"started": False, "error": None}
        assert manager.running is False


async def test_stop_cancels_running_task(tmp_path: Path) -> None:
    state = RuntimeState()
    env_file = _write_valid_env(tmp_path)
    with patch("api.bot_manager.QminBot", _SlowBot):
        manager = BotManager(env_file=env_file, state=state)
        await manager.start()
        assert manager.running is True
        await manager.stop()
        assert manager.running is False


async def test_credentials_reloaded_from_env_each_start(tmp_path: Path) -> None:
    """运行时改 .env 里的 secret，不重启进程、直接 start → 用新值。"""
    state = RuntimeState()
    env_file = _write_valid_env(tmp_path)
    _SuccessBot.instances.clear()

    with patch("api.bot_manager.QminBot", _SuccessBot):
        manager = BotManager(env_file=env_file, state=state)

        # 第一次 start：用 secret-1
        await manager.start()
        assert _SuccessBot.instances[0].app_secret == "secret-1"
        await asyncio.sleep(0)

        # 改 .env 里的 secret，重启 manager 生命周期
        env_file.write_text(
            "APP_ID=id-1\nAPP_SECRET=secret-2\n"
            "ADMIN_TOKEN=toxxxxxxkenneth\n"
            "HOST=127.0.0.1\nPORT=8000\n",
            encoding="utf-8",
        )
        manager2 = BotManager(env_file=env_file, state=state)
        await manager2.start()
        assert _SuccessBot.instances[1].app_secret == "secret-2"


async def test_missing_credentials_returns_error_and_no_bot_constructed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """.env 缺凭证 → started=false，不构造 QminBot。"""
    import api.bot_manager as bm_mod

    called = {"n": 0}

    class _CountBot:
        def __init__(self, *args: object, **kwargs: object) -> None:
            called["n"] += 1

        async def start(self) -> None:
            return

        async def stop(self) -> None:
            return

    monkeypatch.setattr(bm_mod, "QminBot", _CountBot)

    state = RuntimeState()
    env_file = _write_invalid_env(tmp_path)
    manager = bm_mod.BotManager(env_file=env_file, state=state)

    result = await manager.start()
    assert result["started"] is False
    assert "配置不完整" in str(result["error"])
    assert "APP_ID" in str(result["error"])
    assert called["n"] == 0  # 关键：QminBot 不应被构造
    assert manager.running is False


async def test_delayed_exception_triggers_done_callback_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_START_WINDOW 之后才抛的异常 → start 返回 started=True，done callback 写 ERROR。"""
    import api.bot_manager as bm_mod
    from pathlib import Path as _Path

    monkeypatch.setattr(bm_mod.BotManager, "_START_WINDOW", 0.05)

    class _DelayedFailBot:
        def __init__(self, *, app_id: str, app_secret: str, state: object) -> None:
            self.app_id = app_id
            self.app_secret = app_secret

        async def start(self) -> None:
            await asyncio.sleep(0.15)  # 超过 0.05s 窗口才抛
            raise RuntimeError("boom")

        async def stop(self) -> None:
            return

    state = RuntimeState()
    monkeypatch.setattr(bm_mod, "QminBot", _DelayedFailBot)
    env_file = _write_valid_env(tmp_path)
    manager = bm_mod.BotManager(env_file=env_file, state=state)

    result = await manager.start()
    assert result == {"started": True, "error": None}

    await asyncio.sleep(0.3)

    assert manager.running is False
    snapshot = state.snapshot()
    assert snapshot.log_count == 1
    log = state.recent_logs()[0]
    assert log.level == "ERROR"
    assert "机器人异常退出" in log.message
    assert "RuntimeError" in log.message
    assert "boom" in log.message


# ---------- HTTP 路由 ----------
async def test_api_bot_routes_forward_to_manager(
    tmp_path: Path,
) -> None:
    """HTTP 层验证 /api/bot 路由正确转发给 BotManager。"""
    import httpx

    from api.main import create_app
    from core.config import load_settings

    env_file = _write_valid_env(tmp_path)
    state = RuntimeState()

    class _DummyBot:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def start(self) -> None:
            return

        async def stop(self) -> None:
            return

    with patch("api.bot_manager.QminBot", _DummyBot):
        settings = load_settings(env_file)
        bm = BotManager(env_file=env_file, state=state)
        plugin_dir = tmp_path / "plugins"
        plugin_dir.mkdir(exist_ok=True)
        app = create_app(
            settings=settings,
            plugin_dir=plugin_dir,
            env_file=env_file,
            bot_manager=bm,
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            r = await client.get("/api/bot")
            assert r.status_code == 401

            r = await client.get(
                "/api/bot",
                headers={"X-Admin-Token": "toxxxxxxkenneth"},
            )
            assert r.status_code == 200
            assert r.json() == {"running": False}

            r = await client.post(
                "/api/bot/start",
                headers={"X-Admin-Token": "toxxxxxxkenneth"},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["started"] is True
            assert body["error"] is None


async def test_api_bot_routes_without_manager_returns_409(
    tmp_path: Path,
) -> None:
    """qmin run 模式下没有 bot_manager，路由返回 409。"""
    import httpx

    from api.main import create_app
    from core.config import load_settings

    env_file = _write_valid_env(tmp_path)
    settings = load_settings(env_file)
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir(exist_ok=True)
    app = create_app(
        settings=settings,
        plugin_dir=plugin_dir,
        env_file=env_file,
        bot_manager=None,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as client:
        r = await client.get(
            "/api/bot",
            headers={"X-Admin-Token": "toxxxxxxkenneth"},
        )
        assert r.status_code == 409
