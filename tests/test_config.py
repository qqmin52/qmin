"""core/config.py 的单元测试。

全部使用 ``tmp_path`` 生成临时 ``.env``，并通过 ``monkeypatch`` 清空同名环境变量，
保证用例之间、以及与宿主机环境之间互不干扰。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from core.config import (
    ConfigError,
    Settings,
    ensure_admin_token,
    load_settings,
    missing_config_hint,
    read_env_file,
    write_env_file,
)

# 与 core/config.py 的 _ENV_KEYS 对齐，测试前逐个清除。
_ENV_KEYS = ("APP_ID", "APP_SECRET", "ADMIN_TOKEN", "HOST", "PORT", "LOG_LEVEL", "DB_PATH")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清除可能干扰断言的同名环境变量。"""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def write_env(tmp_path: Path, text: str) -> Path:
    """写入临时 .env 并返回路径。"""
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")
    return env_file


def test_write_env_file_is_readable_and_leaves_no_temp(tmp_path: Path) -> None:
    """write_env_file 写入的内容能被 load_settings 读回，且无临时文件残留。"""
    env_file = tmp_path / ".env"

    write_env_file(
        env_file,
        {
            "APP_ID": "102345678",
            "APP_SECRET": "abcdef123456",
            "ADMIN_TOKEN": "token-abcdefghijklmn",
            "PORT": "9000",
        },
    )

    content = env_file.read_text(encoding="utf-8")
    assert content.startswith("# Qmin 配置（由 qmin init 生成）")

    settings = load_settings(env_file)
    assert settings.app_id == "102345678"
    assert settings.app_secret.get_secret_value() == "abcdef123456"
    assert settings.admin_token.get_secret_value() == "token-abcdefghijklmn"
    assert settings.port == 9000

    leftovers = [path.name for path in tmp_path.iterdir() if path.name != ".env"]
    assert leftovers == []


def test_read_env_file_returns_empty_when_missing(tmp_path: Path) -> None:
    """read_env_file 在文件不存在时返回空字典。"""
    assert read_env_file(tmp_path / ".env") == {}


def test_read_env_file_parses_comments_and_quotes(tmp_path: Path) -> None:
    """read_env_file 与 load_settings 使用同一套解析规则。"""
    env_file = write_env(
        tmp_path,
        "# 注释行\n"
        "\n"
        "  APP_ID  =  102345678  \n"
        'APP_SECRET = "s3cr3t#abc=123"\n'
        "export ADMIN_TOKEN='token-xyz'\n",
    )

    values = read_env_file(env_file)

    assert values == {
        "APP_ID": "102345678",
        "APP_SECRET": "s3cr3t#abc=123",
        "ADMIN_TOKEN": "token-xyz",
    }


def test_load_complete_settings(tmp_path: Path) -> None:
    """.env 完整时能正确加载全部字段，未给出的字段取默认值。"""
    env_file = write_env(
        tmp_path,
        "APP_ID=102345678\n"
        "APP_SECRET=abcdef123456\n"
        "ADMIN_TOKEN=token-abcdefghijklmn\n"
        "PORT=9000\n",
    )

    settings = load_settings(env_file)

    assert settings.app_id == "102345678"
    assert isinstance(settings.app_secret, SecretStr)
    assert settings.app_secret.get_secret_value() == "abcdef123456"
    assert settings.admin_token.get_secret_value() == "token-abcdefghijklmn"
    assert settings.host == "127.0.0.1"
    assert settings.port == 9000
    assert settings.log_level == "INFO"
    assert settings.db_path == Path("qmin.db")


def test_missing_app_secret_raises_config_error(tmp_path: Path) -> None:
    """缺 app_secret 时抛 ConfigError，提示含 app_secret 且不含任何配置值明文。"""
    env_file = write_env(
        tmp_path,
        "APP_ID=102345678\n"
        "ADMIN_TOKEN=super-secret-token-value\n",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_settings(env_file)

    error = exc_info.value
    message = str(error)
    assert error.missing == ["APP_SECRET"]
    assert "app_secret" in message
    assert "APP_SECRET" in message
    # 提示里不得出现任何真实值（含已有项的明文）。
    assert "super-secret-token-value" not in message
    assert "102345678" not in message


def test_missing_config_hint_mentions_each_item() -> None:
    """missing_config_hint 逐项给出说明与 .env 变量名。"""
    hint = missing_config_hint(["APP_ID", "APP_SECRET"])

    assert "app_id" in hint
    assert "app_secret" in hint
    assert "APP_ID" in hint
    assert "APP_SECRET" in hint
    assert ".env" in hint


def test_masked_secret() -> None:
    """masked_secret 保留末 4 位；空值与过短值只返回 ****。"""
    base = {"app_id": "1", "admin_token": "t"}

    assert Settings(app_secret="abcdef123456", **base).masked_secret() == "****3456"
    assert Settings(app_secret="", **base).masked_secret() == "****"
    assert Settings(app_secret="abcd", **base).masked_secret() == "****"


def test_to_public_dict_never_leaks_plaintext() -> None:
    """to_public_dict 中 secret 打码、令牌只暴露布尔值。"""
    settings = Settings(
        app_id="102345678",
        app_secret="plainsecret-9999",
        admin_token="admin-token-do-not-leak",
        port=8000,
    )

    public = settings.to_public_dict()
    serialized = str(public)

    assert public["app_secret"] == "****9999"
    assert public["admin_token_set"] is True
    assert "admin_token" not in public
    assert "plainsecret-9999" not in serialized
    assert "admin-token-do-not-leak" not in serialized
    assert public["app_id"] == "102345678"


def test_ensure_admin_token_generates_new_token(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """缺 admin_token 时生成新令牌，写回 .env 且仅在控制台打印一次。"""
    env_file = write_env(
        tmp_path,
        "APP_ID=102345678\n"
        "APP_SECRET=abcdef123456\n",
    )

    token = ensure_admin_token(env_file)

    assert token is not None
    assert 40 <= len(token) <= 64
    content = env_file.read_text(encoding="utf-8")
    assert f"ADMIN_TOKEN={token}" in content
    # 原有内容保持不动。
    assert "APP_ID=102345678" in content
    assert "APP_SECRET=abcdef123456" in content
    # 原子写不留下临时文件。
    assert list(tmp_path.glob(".*.tmp")) == []
    # 生成后可以正常加载。
    assert load_settings(env_file).admin_token.get_secret_value() == token
    # 控制台只打印一次。
    captured = capsys.readouterr()
    assert captured.out.count(token) == 1


def test_ensure_admin_token_keeps_existing_file_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """已有 admin_token 时返回 None，文件内容与 mtime 均不变。"""
    env_file = write_env(
        tmp_path,
        "APP_ID=102345678\n"
        "APP_SECRET=abcdef123456\n"
        "ADMIN_TOKEN=existing-token-keep-me\n",
    )
    before_bytes = env_file.read_bytes()
    before_mtime = env_file.stat().st_mtime_ns

    assert ensure_admin_token(env_file) is None
    assert env_file.read_bytes() == before_bytes
    assert env_file.stat().st_mtime_ns == before_mtime
    assert capsys.readouterr().out == ""


def test_ensure_admin_token_creates_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """.env 不存在时能创建文件；随后 load_settings 仍因缺 app_id 失败。"""
    env_file = tmp_path / ".env"
    assert not env_file.exists()

    token = ensure_admin_token(env_file)

    assert token is not None
    assert env_file.exists()
    content = env_file.read_text(encoding="utf-8")
    assert f"ADMIN_TOKEN={token}" in content

    with pytest.raises(ConfigError) as exc_info:
        load_settings(env_file)

    message = str(exc_info.value)
    assert "app_id" in message
    assert "app_secret" in message
    assert token not in message
    assert capsys.readouterr().out.count(token) == 1


def test_parse_comments_blank_lines_and_quotes(tmp_path: Path) -> None:
    """注释行、空行、两侧空格、单双引号与 export 前缀均能正确解析。"""
    env_file = write_env(
        tmp_path,
        "# Qmin 测试配置\n"
        "\n"
        "  APP_ID  =  102345678  \n"
        "\n"
        "# 下面这行引号内包含 # 与 =\n"
        'APP_SECRET = "s3cr3t#abc=123"\n'
        "export ADMIN_TOKEN='token-xyz'\n"
        "LOG_LEVEL = debug\n",
    )

    settings = load_settings(env_file)

    assert settings.app_id == "102345678"
    assert settings.app_secret.get_secret_value() == "s3cr3t#abc=123"
    assert settings.admin_token.get_secret_value() == "token-xyz"
    assert settings.log_level == "DEBUG"


def test_env_var_overrides_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同名环境变量优先于 .env，便于容器部署覆盖。"""
    env_file = write_env(
        tmp_path,
        "APP_ID=102345678\n"
        "APP_SECRET=abcdef123456\n"
        "ADMIN_TOKEN=token-from-file\n"
        "PORT=8001\n",
    )
    monkeypatch.setenv("PORT", "9001")

    assert load_settings(env_file).port == 9001


def test_invalid_port_raises_readable_error(tmp_path: Path) -> None:
    """非法 PORT 抛中文 ConfigError，而不是裸 pydantic 报错。"""
    env_file = write_env(
        tmp_path,
        "APP_ID=102345678\n"
        "APP_SECRET=abcdef123456\n"
        "ADMIN_TOKEN=token-abcdefghijklmn\n"
        "PORT=not-a-number\n",
    )

    with pytest.raises(ConfigError) as exc_info:
        load_settings(env_file)

    assert exc_info.value.missing == ["PORT"]
    assert "PORT" in str(exc_info.value)
