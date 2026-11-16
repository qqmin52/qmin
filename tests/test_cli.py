"""core/cli.py 的测试。

使用 typer.testing.CliRunner，所有用例在 ``tmp_path`` 中运行，不触碰项目根目录的 .env。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import core.cli
from core.config import load_settings
from core.handlers import router
from core.state import reset_state

runner = CliRunner()

_ENV_KEYS = ("APP_ID", "APP_SECRET", "ADMIN_TOKEN", "HOST", "PORT", "LOG_LEVEL", "DB_PATH")

COMPLETE_ENV = (
    "APP_ID=102345678\n"
    "APP_SECRET=secret-value\n"
    "ADMIN_TOKEN=token-value\n"
    "HOST=127.0.0.1\n"
    "PORT=8000\n"
    "LOG_LEVEL=INFO\n"
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """切换工作目录、清理状态与同名环境变量。"""
    reset_state()
    router.clear()
    monkeypatch.chdir(tmp_path)
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield
    router.clear()
    reset_state()


def test_init_creates_env_file() -> None:
    """init 在空目录生成 .env，含 APP_ID 与自动生成的 ADMIN_TOKEN。"""
    result = runner.invoke(
        core.cli.app,
        ["init"],
        input="102345678\nsecret-value\n\n\n\n\n",
    )

    assert result.exit_code == 0, result.output
    env_file = Path(".env")
    content = env_file.read_text(encoding="utf-8")
    assert "APP_ID=102345678" in content
    assert "ADMIN_TOKEN=" in content
    assert "DB_PATH=qmin.db" in content

    settings = load_settings(env_file)
    assert settings.app_id == "102345678"
    assert settings.app_secret.get_secret_value() == "secret-value"
    assert settings.admin_token.get_secret_value()


def test_init_declined_overwrite_keeps_file() -> None:
    """已存在 .env 且拒绝覆盖时文件内容不变。"""
    env_file = Path(".env")
    env_file.write_text("APP_ID=keep-me\n", encoding="utf-8")
    before = env_file.read_bytes()

    result = runner.invoke(core.cli.app, ["init"], input="n\n")

    assert result.exit_code == 0, result.output
    assert env_file.read_bytes() == before


def test_doctor_reports_missing_config() -> None:
    """无配置时 doctor 退出码为 1，提示缺 app_id 且不泄漏任何真实密钥。"""
    result = runner.invoke(core.cli.app, ["doctor"])

    assert result.exit_code == 1
    assert "app_id" in result.output

    Path(".env").write_text(
        "APP_ID=102345678\nAPP_SECRET=super-secret-value\n", encoding="utf-8"
    )

    partial = runner.invoke(core.cli.app, ["doctor"])

    assert partial.exit_code == 1
    assert "admin_token" in partial.output
    assert "super-secret-value" not in partial.output
    assert "super-secret-value" not in result.output


def test_doctor_reports_complete_config() -> None:
    """配置完整时 doctor 退出码为 0，输出含 OK。"""
    Path(".env").write_text(COMPLETE_ENV, encoding="utf-8")

    result = runner.invoke(core.cli.app, ["doctor"])

    assert result.exit_code == 0, result.output
    assert "OK" in result.output


def test_run_without_config_exits_before_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配置缺失时 run 退出码为 1，且不构造 QminBot。"""
    created: list[dict[str, object]] = []

    class RecordingBot:
        def __init__(self, **kwargs: object) -> None:
            created.append(kwargs)

    monkeypatch.setattr(core.cli, "QminBot", RecordingBot)

    result = runner.invoke(core.cli.app, ["run"])

    assert result.exit_code == 1
    assert created == []


def test_run_loads_plugins_and_starts_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    """配置完整时 run 加载插件、启动机器人并同时启动管理 API。"""
    Path(".env").write_text(COMPLETE_ENV, encoding="utf-8")

    plugin_calls: list[Path] = []

    async def fake_load_plugins(plugin_dir: Path) -> list[object]:
        plugin_calls.append(plugin_dir)
        return []

    create_calls: list[tuple[object, Path]] = []

    def fake_create_app(*, settings: object, plugin_dir: Path) -> object:
        create_calls.append((settings, plugin_dir))
        return object()

    class FakeServer:
        instances: list["FakeServer"] = []

        def __init__(self, config: object) -> None:
            self.config = config
            self.should_exit = False
            self.serve_calls = 0
            FakeServer.instances.append(self)

        async def serve(self) -> None:
            self.serve_calls += 1

    created: list["FakeBot"] = []

    class FakeBot:
        def __init__(self, *, app_id: str, app_secret: str) -> None:
            self.app_id = app_id
            self.app_secret = app_secret
            self.start_calls = 0
            self.stop_calls = 0
            created.append(self)

        async def start(self) -> None:
            self.start_calls += 1

        async def stop(self) -> None:
            self.stop_calls += 1

    monkeypatch.setattr(core.cli, "load_plugins", fake_load_plugins)
    monkeypatch.setattr(core.cli, "QminBot", FakeBot)
    monkeypatch.setattr(core.cli, "create_app", fake_create_app)
    monkeypatch.setattr(core.cli.uvicorn, "Server", FakeServer)

    result = runner.invoke(core.cli.app, ["run"])

    assert result.exit_code == 0, result.output
    assert "管理面板: http://127.0.0.1:8000" in result.output
    assert len(plugin_calls) == 1
    assert len(create_calls) == 1

    assert len(FakeServer.instances) == 1
    server = FakeServer.instances[0]
    assert server.serve_calls == 1
    assert server.should_exit is True

    assert len(created) == 1
    bot = created[0]
    assert bot.app_id == "102345678"
    assert bot.start_calls == 1
    assert bot.stop_calls == 1


def test_api_without_config_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    """无配置时 api 退出码为 1，且不启动 uvicorn。"""
    run_calls: list[tuple[object, dict[str, object]]] = []

    def fake_run(app: object, **kwargs: object) -> None:
        run_calls.append((app, kwargs))

    monkeypatch.setattr(core.cli.uvicorn, "run", fake_run)

    result = runner.invoke(core.cli.app, ["api"])

    assert result.exit_code == 1
    assert run_calls == []
    assert "app_id" in result.output


def test_api_starts_panel_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """api 只启动管理面板：加载插件、构建应用、不构造 QminBot。"""
    Path(".env").write_text(COMPLETE_ENV, encoding="utf-8")

    plugin_calls: list[Path] = []

    async def fake_load_plugins(plugin_dir: Path) -> list[object]:
        plugin_calls.append(plugin_dir)
        return []

    create_calls: list[tuple[object, Path]] = []

    def fake_create_app(*, settings: object, plugin_dir: Path) -> object:
        create_calls.append((settings, plugin_dir))
        return object()

    run_calls: list[dict[str, object]] = []

    def fake_run(app: object, **kwargs: object) -> None:
        run_calls.append({"app": app, **kwargs})

    class ExplodingBot:
        def __init__(self, **kwargs: object) -> None:
            raise AssertionError("api 命令不得构造 QminBot")

    monkeypatch.setattr(core.cli, "load_plugins", fake_load_plugins)
    monkeypatch.setattr(core.cli, "create_app", fake_create_app)
    monkeypatch.setattr(core.cli.uvicorn, "run", fake_run)
    monkeypatch.setattr(core.cli, "QminBot", ExplodingBot)

    result = runner.invoke(core.cli.app, ["api"])

    assert result.exit_code == 0, result.output
    assert "管理面板: http://127.0.0.1:8000" in result.output

    assert len(plugin_calls) == 1
    assert plugin_calls[0] == Path("plugins")
    assert len(create_calls) == 1

    assert len(run_calls) == 1
    assert run_calls[0]["host"] == "127.0.0.1"
    assert run_calls[0]["port"] == 8000
    assert run_calls[0]["log_level"] == "info"
