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
    assert "qmin start" in result.output
    assert "qmin token" in result.output

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


def test_start_without_config_enters_setup_wizard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配置缺失时 start 用占位配置启动面板，且不自动连接机器人。"""
    create_calls: list[dict[str, object]] = []

    def fake_create_app(**kwargs: object) -> object:
        create_calls.append(kwargs)
        return object()

    run_calls: list[dict[str, object]] = []

    def fake_run(app: object, **kwargs: object) -> None:
        run_calls.append({"app": app, **kwargs})

    monkeypatch.setattr(core.cli, "create_app", fake_create_app)
    monkeypatch.setattr(core.cli.uvicorn, "run", fake_run)

    result = runner.invoke(core.cli.app, ["start"])

    assert result.exit_code == 0, result.output
    assert "配置不完整" in result.output
    assert "配置向导" in result.output
    assert len(run_calls) == 1
    assert create_calls[0]["auto_start_bot"] is False
    assert create_calls[0]["bot_manager"] is not None


def test_start_with_config_autostarts_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配置完整时创建应用并传 auto_start_bot=True，CLI 自己不启动机器人。"""
    Path(".env").write_text(COMPLETE_ENV, encoding="utf-8")

    plugin_calls: list[Path] = []

    async def fake_load_plugins(plugin_dir: Path) -> list[object]:
        plugin_calls.append(plugin_dir)
        return []

    create_calls: list[dict[str, object]] = []

    def fake_create_app(**kwargs: object) -> object:
        create_calls.append(kwargs)
        return object()

    run_calls: list[dict[str, object]] = []

    def fake_run(app: object, **kwargs: object) -> None:
        run_calls.append({"app": app, **kwargs})

    monkeypatch.setattr(core.cli, "load_plugins", fake_load_plugins)
    monkeypatch.setattr(core.cli, "create_app", fake_create_app)
    monkeypatch.setattr(core.cli.uvicorn, "run", fake_run)

    result = runner.invoke(core.cli.app, ["start"])

    assert result.exit_code == 0, result.output
    assert "管理面板: http://127.0.0.1:8000" in result.output
    assert "正在连接机器人" in result.output
    assert plugin_calls == [Path("plugins")]
    assert create_calls[0]["auto_start_bot"] is True
    assert create_calls[0]["bot_manager"] is not None
    # 机器人生命周期交给 lifespan，CLI 层不得直接构造 QminBot。
    assert not hasattr(core.cli, "QminBot")
    assert run_calls[0]["host"] == "127.0.0.1"
    assert run_calls[0]["port"] == 8000
    assert run_calls[0]["log_level"] == "info"


def test_legacy_commands_removed() -> None:
    """旧版 api / run 已合并为 start，不再存在。"""
    for legacy in ("api", "run"):
        result = runner.invoke(core.cli.app, [legacy])
        assert result.exit_code != 0
        assert "No such command" in result.output


def test_token_copies_to_clipboard(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认复制到剪贴板，输出不含令牌明文。"""
    Path(".env").write_text("ADMIN_TOKEN=token-value\n", encoding="utf-8")
    monkeypatch.setattr(core.cli, "_copy_to_clipboard", lambda text: True)

    result = runner.invoke(core.cli.app, ["token"])

    assert result.exit_code == 0, result.output
    assert "已复制" in result.output
    assert "token-value" not in result.output


def test_token_show_prints_plaintext() -> None:
    """--show 直接打印明文，供脚本或无剪贴板环境使用。"""
    Path(".env").write_text("ADMIN_TOKEN=token-value\n", encoding="utf-8")

    result = runner.invoke(core.cli.app, ["token", "--show"])

    assert result.exit_code == 0, result.output
    assert "token-value" in result.output


def test_token_without_admin_token_exits_1() -> None:
    """既无 .env 令牌也无环境变量时退出码为 1，并提示先 init。"""
    result = runner.invoke(core.cli.app, ["token"])

    assert result.exit_code == 1
    assert "qmin init" in result.output


def test_token_falls_back_to_plaintext_when_clipboard_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """剪贴板不可用时降级打印明文并提示手动复制。"""
    Path(".env").write_text("ADMIN_TOKEN=token-value\n", encoding="utf-8")
    monkeypatch.setattr(core.cli, "_copy_to_clipboard", lambda text: False)

    result = runner.invoke(core.cli.app, ["token"])

    assert result.exit_code == 0, result.output
    assert "请手动复制" in result.output
    assert "token-value" in result.output


def test_token_reads_environment_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env` 没有令牌时回退到进程环境变量。"""
    monkeypatch.setenv("ADMIN_TOKEN", "env-token")

    result = runner.invoke(core.cli.app, ["token", "--show"])

    assert result.exit_code == 0, result.output
    assert "env-token" in result.output


def test_copy_to_clipboard_swallows_missing_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """剪贴板命令不存在时返回 False，不把异常抛给用户。"""

    def fake_run(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("clip")

    monkeypatch.setattr(core.cli.subprocess, "run", fake_run)

    assert core.cli._copy_to_clipboard("token") is False
