"""配置模块。

职责：从项目根目录的 ``.env`` 读取 QQ 官方开放平台凭据与本地运行参数，
并在配置缺失时给出面向人类的中文提示，而不是抛出 pydantic 原始报错。

约定：

- 只读 ``.env`` 与进程环境变量（同名时环境变量优先，便于容器部署覆盖），不主动改写。
- 同步写 ``.env`` 只允许两个入口：
  * :func:`ensure_admin_token` —— CLI 启动路径专用，生成后打印到控制台。
  * :func:`generate_admin_token` —— CLI 与 FastAPI 路由通用，原子写，不打印不记日志。
- ``app_secret`` / ``admin_token`` 均使用 :class:`pydantic.SecretStr` 承载，
  避免日志、异常、``repr()`` 中泄漏明文。
- 本模块不依赖 ``api/``，也不依赖 ``botpy``。
"""

from __future__ import annotations

import os
import re
import secrets
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, ValidationError

# 项目内置默认值：管理接口默认只监听本机回环地址（安全基线）。
DEFAULT_HOST: str = "127.0.0.1"
DEFAULT_PORT: int = 8000
DEFAULT_DB_PATH: str = "qmin.db"

# qmin api 占位模式下 Settings 的 admin_token 字段填这个哨兵值。
# 它永远不被视为合法令牌（api/deps.py 会显式拒绝）。
UNCONFIGURED_TOKEN: str = "unconfigured"

# 必填项，顺序即提示里展示的条目顺序。
REQUIRED_KEYS: tuple[str, ...] = ("APP_ID", "APP_SECRET", "ADMIN_TOKEN")

# 全部受支持的配置项。
_ENV_KEYS: tuple[str, ...] = (
    "APP_ID",
    "APP_SECRET",
    "ADMIN_TOKEN",
    "HOST",
    "PORT",
    "LOG_LEVEL",
    "DB_PATH",
    "LOG_MAX_ROWS",
    "LOG_SDK",
    "LOG_MESSAGE_CONTENT",
)

# 每个必填项的填写指引（只含示例占位，不含任何真实密钥）。
_KEY_GUIDES: dict[str, str] = {
    "APP_ID": "QQ 开放平台 → 机器人 → 开发设置 → AppID，形如 APP_ID=102345678",
    "APP_SECRET": "同一页面的 AppSecret，形如 APP_SECRET=你的密钥",
    "ADMIN_TOKEN": "管理接口写操作令牌，执行 `qmin init` 会自动生成",
}

# 定位已有的 ADMIN_TOKEN 行（空值也算已存在，但会被视为缺失并就地替换）。
_ADMIN_TOKEN_LINE = re.compile(r"^[ \t]*ADMIN_TOKEN[ \t]*=.*$", re.MULTILINE)


class ConfigError(RuntimeError):
    """配置缺失或不合法时抛出。

    Attributes:
        missing: 缺失或不合法的配置项名称（环境变量风格，例如 ``APP_SECRET``）。
        hint: 面向人类的中文修复提示，可直接打印。

    Notes:
        构造时只接收配置项名称与提示文本，禁止把配置值传入，
        以免异常信息（含 traceback）中出现 AppSecret / 管理令牌明文。
    """

    def __init__(self, missing: list[str], hint: str) -> None:
        """初始化异常。

        Args:
            missing: 缺失或不合法的配置项名称列表。
            hint: 中文修复提示，直接打印给使用者看。
        """
        self.missing: list[str] = list(missing)
        self.hint: str = hint
        super().__init__(hint)

    def __str__(self) -> str:
        """返回中文可读的错误描述（缺失项 + 修复提示）。"""
        return self.hint


class Settings(BaseModel):
    """框架运行配置。

    字段与 ``.env`` 中的环境变量一一对应（大写），由 :func:`load_settings` 填充。
    敏感字段使用 :class:`SecretStr`，``repr()`` / 日志中自动显示为 ``**********``。
    """

    app_id: str = Field(description="QQ 开放平台机器人 AppID")
    app_secret: SecretStr = Field(description="QQ 开放平台机器人 AppSecret，禁止明文外传")
    admin_token: SecretStr = Field(description="管理接口写操作令牌，禁止明文外传")
    host: str = Field(default=DEFAULT_HOST, description="管理接口监听地址，默认仅本机")
    port: int = Field(default=DEFAULT_PORT, description="管理接口监听端口")
    log_level: str = Field(default="INFO", description="日志级别，如 DEBUG/INFO/WARNING")
    db_path: Path = Field(default=Path(DEFAULT_DB_PATH), description="SQLite 数据库文件路径")
    log_max_rows: int = Field(default=50000, ge=1, description="日志表最多保留的行数")
    log_sdk: Literal["off", "all"] = Field(
        default="off", description="SDK 日志导流级别：off 只导 WARNING+，all 也导 INFO"
    )
    log_message_content: bool = Field(
        default=True, description="入站消息日志是否记录正文（false 只记录会话）"
    )

    def masked_secret(self) -> str:
        """返回打码后的 AppSecret，用于 ``GET /api/config`` 等只读场景。

        Returns:
            空值或长度不足 5 位时返回 ``****``；否则返回 ``****`` + 末 4 位。
        """
        secret = self.app_secret.get_secret_value()
        if len(secret) <= 4:
            return "****"
        return f"****{secret[-4:]}"

    def to_public_dict(self) -> dict[str, object]:
        """返回可安全下发给前端的配置字典。

        Returns:
            键名与 :class:`api.schema.ConfigOut` 对齐；``app_secret`` 恒为打码值，
            管理令牌只以 ``admin_token_set`` 布尔值体现，绝不回传明文。
        """
        return {
            "app_id": self.app_id,
            "app_secret": self.masked_secret(),
            "host": self.host,
            "port": self.port,
            "log_level": self.log_level,
            "db_path": str(self.db_path),
            "admin_token_set": bool(self.admin_token.get_secret_value()),
        }


def load_settings(env_file: Path = Path(".env")) -> Settings:
    """加载并校验配置。

    解析顺序：先读 ``.env``，再用进程环境变量覆盖同名项（空值环境变量不覆盖）。

    Args:
        env_file: ``.env`` 文件路径；文件不存在时仅依赖进程环境变量。

    Returns:
        校验通过的 :class:`Settings` 实例。

    Raises:
        ConfigError: 必填项缺失或取值不合法，异常内含中文修复提示。
    """
    raw: dict[str, str] = dict(_parse_env_file(env_file)) if env_file.exists() else {}
    for key in _ENV_KEYS:
        value = os.environ.get(key)
        if value is not None and value.strip():
            raw[key] = value.strip()

    missing = [key for key in REQUIRED_KEYS if not raw.get(key, "").strip()]
    if missing:
        raise ConfigError(missing, missing_config_hint(missing))

    port = _parse_port(raw.get("PORT", ""))
    try:
        return Settings(
            app_id=raw["APP_ID"].strip(),
            app_secret=raw["APP_SECRET"].strip(),
            admin_token=raw["ADMIN_TOKEN"].strip(),
            host=raw.get("HOST", "").strip() or DEFAULT_HOST,
            port=port,
            log_level=raw.get("LOG_LEVEL", "").strip().upper() or "INFO",
            db_path=Path(raw.get("DB_PATH", "").strip() or DEFAULT_DB_PATH),
            log_max_rows=_parse_positive_int(
                raw.get("LOG_MAX_ROWS", ""), "LOG_MAX_ROWS", 50000
            ),
            log_sdk=_parse_sdk_mode(raw.get("LOG_SDK", "")),
            log_message_content=_parse_bool(
                raw.get("LOG_MESSAGE_CONTENT", ""), "LOG_MESSAGE_CONTENT", True
            ),
        )
    except ValidationError as exc:
        # 只提取字段名，绝不把字段值拼进错误信息。
        fields = sorted(
            {str(error["loc"][0]).upper() for error in exc.errors() if error.get("loc")}
        )
        raise ConfigError(
            fields, f"以下配置项格式不合法：{', '.join(fields)}，请检查 .env 中对应行。"
        ) from None


def missing_config_hint(missing: list[str]) -> str:
    """把缺失项渲染成中文多行提示。

    Args:
        missing: 缺失的配置项名称列表。

    Returns:
        可直接打印的中文提示文本，说明缺什么、去哪儿拿、怎么填。
    """
    lines = ["缺少必要的 QQ 机器人配置，请检查项目根目录的 .env 文件："]
    for index, key in enumerate(missing, start=1):
        display = key.lower()
        guide = _KEY_GUIDES.get(key, "请在 .env 中补上该项")
        lines.append(f"  {index}. {display}（.env 变量名 {key}）：{guide}")
    lines.append("提示：先执行 `qmin init` 可按模板生成 .env，并自动生成管理令牌。")
    return "\n".join(lines)


def generate_admin_token(env_file: Path = Path(".env")) -> str:
    """生成并原子写回一个全新的 ADMIN_TOKEN；已存在则在原行上替换。

    允许在 CLI 启动路径与 FastAPI 路由中调用。纯函数式副作用仅在 ``.env``：
    不打印控制台、不改 RuntimeState、不调用任何网络或日志设施。

    Args:
        env_file: ``.env`` 文件路径；不存在时会被创建。

    Returns:
        新生成的随机令牌（长度 43 的 urlsafe token）。
    """
    token = secrets.token_urlsafe(32)
    content = env_file.read_text(encoding="utf-8") if env_file.exists() else ""

    if _ADMIN_TOKEN_LINE.search(content):
        content = _ADMIN_TOKEN_LINE.sub(
            lambda _: f"ADMIN_TOKEN={token}", content, count=1
        )
    else:
        if content and not content.endswith("\n"):
            content += "\n"
        if content:
            content += "\n"
        content += "# 管理接口写操作令牌，首次启动自动生成，请勿提交到版本库\n"
        content += f"ADMIN_TOKEN={token}\n"

    _atomic_write(env_file, content)
    return token


def ensure_admin_token(env_file: Path = Path(".env")) -> str | None:
    """CLI 启动路径专用：缺失时调用 :func:`generate_admin_token` 生成并打印到控制台。

    仅限 CLI 启动路径（``qmin init`` / ``qmin run``）。FastAPI 路由中如需生成令牌，
    应直接调用 :func:`generate_admin_token`，它不会向控制台打印明文。

    Args:
        env_file: ``.env`` 文件路径；不存在时会被创建。

    Returns:
        新生成的令牌；``.env`` 中已有非空 ``ADMIN_TOKEN`` 时返回 ``None`` 且文件不变。
    """
    existing = _parse_env_file(env_file).get("ADMIN_TOKEN", "").strip()
    if existing:
        return None

    token = generate_admin_token(env_file)
    print(f"已生成管理令牌，请查看 .env 或控制台输出：ADMIN_TOKEN={token}")
    return token


def write_env_file(path: Path, values: Mapping[str, str]) -> None:
    """把配置写入 ``.env``（原子写）。

    Args:
        path: 目标 ``.env`` 路径；父目录必须已存在。
        values: 环境变量名到值的映射，按插入顺序逐行写出。

    Notes:
        文件首行为固定注释；写入方式为同目录临时文件 → fsync → ``os.replace``，
        POSIX 下新建文件权限为 ``0600``。值按原样写入，不做转义。
    """
    lines = ["# Qmin 配置（由 qmin init 生成）"]
    lines.extend(f"{key}={value}" for key, value in values.items())
    _atomic_write(path, "\n".join(lines) + "\n")


def read_env_file(env_file: Path) -> dict[str, str]:
    """读取 ``.env`` 为键值字典。

    Args:
        env_file: ``.env`` 文件路径；不存在时返回空字典。

    Returns:
        环境变量名到值的映射，解析规则与 :func:`load_settings` 一致。
    """
    return dict(_parse_env_file(env_file))


def _parse_env_file(env_file: Path) -> dict[str, str]:
    """用标准库解析 ``.env``。

    支持：空行、``#`` 整行注释、``export`` 前缀、``KEY = VALUE`` 两侧空格、
    单/双引号包裹（引号内的 ``#``、``=`` 原样保留）。不处理行尾内联注释。

    Args:
        env_file: ``.env`` 文件路径；不存在时返回空字典。

    Returns:
        环境变量名到值的映射；同名键后者覆盖前者。
    """
    if not env_file.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        values[key] = _unquote(value.strip())
    return values


def _unquote(value: str) -> str:
    """去掉成对的单/双引号，其它情况原样返回。

    Args:
        value: 原始值（已去除两侧空白）。

    Returns:
        去引号后的值。
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_port(value: str) -> int:
    """解析端口，非法时抛带中文提示的 :class:`ConfigError`。

    Args:
        value: ``PORT`` 原始值；空字符串表示使用默认端口。

    Returns:
        合法端口号。

    Raises:
        ConfigError: 非整数或超出 1-65535。
    """
    if not value.strip():
        return DEFAULT_PORT
    try:
        port = int(value.strip())
    except ValueError:
        raise ConfigError(
            ["PORT"], "PORT 必须是 1-65535 之间的整数，请检查 .env 中的 PORT 行。"
        ) from None
    if not 1 <= port <= 65535:
        raise ConfigError(
            ["PORT"], "PORT 必须是 1-65535 之间的整数，请检查 .env 中的 PORT 行。"
        )
    return port


def _parse_positive_int(value: str, key: str, default: int) -> int:
    """解析正整数配置项；空值用默认值，非法值抛 :class:`ConfigError`。

    Args:
        value: 原始值。
        key: 环境变量名（用于错误提示）。
        default: 空值时采用的默认值。

    Returns:
        正整数。
    """
    if not value.strip():
        return default
    try:
        parsed = int(value.strip())
    except ValueError:
        parsed = 0
    if parsed <= 0:
        raise ConfigError([key], f"{key} 必须是正整数，请检查 .env 中的 {key} 行。")
    return parsed


def _parse_sdk_mode(value: str) -> Literal["off", "all"]:
    """解析 ``LOG_SDK``：只接受 ``off`` / ``all``（不区分大小写），空值默认 ``off``。"""
    mode = value.strip().lower()
    if not mode:
        return "off"
    if mode not in ("off", "all"):
        raise ConfigError(
            ["LOG_SDK"], "LOG_SDK 只能是 off 或 all，请检查 .env 中的 LOG_SDK 行。"
        )
    return mode  # type: ignore[return-value]


def _parse_bool(value: str, key: str, default: bool) -> bool:
    """解析布尔配置项；空值用默认值，非法值抛 :class:`ConfigError`。"""
    text = value.strip().lower()
    if not text:
        return default
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    raise ConfigError(
        [key], f"{key} 只能是 true 或 false，请检查 .env 中的 {key} 行。"
    )


def _atomic_write(path: Path, text: str) -> None:
    """原子写入文本文件：同目录临时文件 → fsync → ``os.replace``。

    Args:
        path: 目标文件路径；父目录必须已存在。
        text: 要写入的完整内容（UTF-8，LF 换行）。

    Notes:
        POSIX 下对新建文件设置 ``0o600``（``mkstemp`` 本身即为 0600，这里显式声明）。
        失败时清理临时文件，避免残留。
    """
    directory = path.parent if str(path.parent) else Path(".")
    existed = path.exists()
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name == "posix" and not existed:
            os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
