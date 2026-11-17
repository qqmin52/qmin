"""命令行入口：``qmin init`` / ``qmin doctor`` / ``qmin start`` / ``qmin token``。

对应 ``pyproject.toml`` 中的 ``qmin = "core.cli:main"``。
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import typer
import uvicorn

from api.bot_manager import BotManager
from api.main import STATIC_DIR, create_app
from core.bot import set_log_message_content
from core.config import (
    ConfigError,
    DEFAULT_DB_PATH,
    DEFAULT_HOST,
    DEFAULT_PORT,
    Settings,
    ensure_admin_token,
    load_settings,
    read_env_file,
    write_env_file,
)
from core.logstore import LogStore
from core.plugins import iter_plugin_files, load_plugins
from core.state import get_state

DEFAULT_ENV_FILE = Path(".env")
DEFAULT_PLUGIN_DIR = Path("plugins")

app = typer.Typer(help="Qmin（简Q）：极简 QQ 官方机器人框架", no_args_is_help=True)


@app.callback()
def _configure(
    ctx: typer.Context,
    env_file: Path = typer.Option(DEFAULT_ENV_FILE, "--env-file", help="配置文件路径"),
    plugin_dir: Path = typer.Option(DEFAULT_PLUGIN_DIR, "--plugin-dir", help="插件目录"),
) -> None:
    """保存全局选项。"""
    ctx.obj = {"env_file": env_file, "plugin_dir": plugin_dir}


def _paths(ctx: typer.Context) -> tuple[Path, Path]:
    """取出全局选项。"""
    data = ctx.obj or {}
    return (
        data.get("env_file", DEFAULT_ENV_FILE),
        data.get("plugin_dir", DEFAULT_PLUGIN_DIR),
    )


def _attach_log_store(panel_app: object, log_store: LogStore) -> None:
    """把日志存储挂到应用状态上；应用 lifespan 启动时会从这里读取。"""
    state = getattr(panel_app, "state", None)
    if state is not None:
        state.log_store = log_store


def _echo_panel_build_hint() -> None:
    """面板构建产物缺失时提示一次构建命令，不影响启动。"""
    if not (STATIC_DIR / "index.html").is_file():
        typer.echo(
            "提示：管理面板未构建，浏览器打开 / 只会看到 JSON 提示。"
            "请先执行：cd webui && npm install && npm run build（Windows 用 npm.cmd）",
            err=True,
        )


@app.command()
def init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="已存在 .env 时直接覆盖"),
) -> None:
    """交互式生成 .env，并自动创建管理令牌。"""
    env_file, _plugin_dir = _paths(ctx)

    if env_file.exists() and not force:
        if not typer.confirm(f"{env_file} 已存在，是否覆盖？", default=False):
            typer.echo("已取消，未修改 .env。")
            return

    app_id = typer.prompt("APP_ID")
    app_secret = typer.prompt("APP_SECRET", hide_input=True)
    host = typer.prompt("HOST", default="127.0.0.1")
    port = typer.prompt("PORT", default="8000")
    log_level = typer.prompt("LOG_LEVEL", default="INFO")
    db_path = typer.prompt(
        "SQLite 路径（管理面板暂无数据库功能，保留默认即可）", default="qmin.db"
    )

    write_env_file(
        env_file,
        {
            "APP_ID": app_id,
            "APP_SECRET": app_secret,
            "HOST": host,
            "PORT": port,
            "LOG_LEVEL": log_level,
            "DB_PATH": db_path,
        },
    )
    ensure_admin_token(env_file)

    typer.echo("下一步：执行 `qmin doctor` 检查配置，再执行 `qmin start` 启动。")
    typer.echo("管理令牌已生成，可用 `qmin token` 复制到剪贴板。")


@app.command()
def doctor(ctx: typer.Context) -> None:
    """检查配置与插件目录（只读，不写文件、不发网络请求）。"""
    env_file, plugin_dir = _paths(ctx)

    try:
        settings = load_settings(env_file)
    except ConfigError as exc:
        typer.echo(exc.hint, err=True)
        raise typer.Exit(1) from None

    checks: list[tuple[bool, str]] = [
        (env_file.exists(), f".env 存在：{env_file}"),
        (bool(settings.app_id), "app_id 已填写"),
        (bool(settings.app_secret.get_secret_value()), "app_secret 已填写"),
        (bool(settings.admin_token.get_secret_value()), "admin_token 已设置"),
    ]
    for passed, label in checks:
        typer.echo(f"{'OK' if passed else 'WARN'}  {label}")

    plugin_dir_ok = plugin_dir.is_dir()
    plugin_files = iter_plugin_files(plugin_dir) if plugin_dir_ok else []
    typer.echo(f"{'OK' if plugin_dir_ok else 'WARN'}  插件目录：{plugin_dir}")
    typer.echo(f"{'OK' if plugin_files else 'WARN'}  插件文件数量：{len(plugin_files)}")

    if not all(passed for passed, _label in checks):
        raise typer.Exit(1)


@app.command()
def start(ctx: typer.Context) -> None:
    """一条命令启动：有配置自动连机器人，没配置进入配置向导。"""
    env_file, plugin_dir = _paths(ctx)

    # 不在此处调用 ensure_admin_token：让首次配置向导 POST /api/setup
    # 成为令牌的唯一生成点，从而可以在那次响应中把明文回传给面板。
    # 启动后每次请求令牌校验都从 .env 最新读取（api/deps.py 的
    # make_admin_token_dependency），setup POST 写入后立刻生效。
    auto = True
    try:
        settings = load_settings(env_file)
    except ConfigError as exc:
        # 首次配置向导场景：app_id / app_secret 缺失也要能启动服务，
        # 让面板通过 /api/setup 完成配置。用占位值构造 Settings 满足类型约束。
        typer.echo(f"配置不完整：{exc}", err=True)
        typer.echo("已进入配置向导模式，请在面板中填写 APP_ID / APP_SECRET。", err=True)
        raw = dict(read_env_file(env_file))
        settings = Settings(
            app_id=raw.get("APP_ID") or "unconfigured",
            app_secret=raw.get("APP_SECRET") or "unconfigured",
            admin_token=raw.get("ADMIN_TOKEN") or "unconfigured",
            host=raw.get("HOST") or DEFAULT_HOST,
            port=int(raw.get("PORT") or str(DEFAULT_PORT)),
            log_level=raw.get("LOG_LEVEL") or "INFO",
            db_path=Path(raw.get("DB_PATH") or DEFAULT_DB_PATH),
        )
        auto = False

    # BotManager 始终构造：配置向导模式下面板也要能手动启停。
    bot_manager = BotManager(
        env_file=env_file,
        state=get_state(),
    )
    set_log_message_content(settings.log_message_content)
    log_store = LogStore(
        settings.db_path,
        max_rows=settings.log_max_rows,
        sdk_mode=settings.log_sdk,
    )

    typer.echo(f"管理面板: http://{settings.host}:{settings.port}")
    if auto:
        typer.echo("正在连接机器人…")
    _echo_panel_build_hint()

    async def _prepare() -> object:
        """加载插件并构建管理面板应用（机器人启动交给 lifespan）。"""
        await load_plugins(plugin_dir)
        panel_app = create_app(
            settings=settings,
            plugin_dir=plugin_dir,
            env_file=env_file,
            bot_manager=bot_manager,
            auto_start_bot=auto,
        )
        # 应用已创建后再注入日志存储（lifespan 启动时从 app.state 读取）。
        _attach_log_store(panel_app, log_store)
        return panel_app

    try:
        # ``uvicorn.run`` 内部会自行调用 asyncio.run；若把它放进协程里执行，
        # 会触发 RuntimeError: asyncio.run() cannot be called from a running event loop，
        # 因此异步准备工作先跑完，再在事件循环之外启动服务。
        panel_app = asyncio.run(_prepare())
        uvicorn.run(
            panel_app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level.lower(),
        )
    except KeyboardInterrupt:
        typer.echo("已停止")
        raise typer.Exit(0) from None


def _copy_to_clipboard(text: str) -> bool:
    """把文本写入系统剪贴板。

    依次尝试当前平台可用的剪贴板命令，任何失败（命令不存在、超时、
    子进程非零退出）都返回 ``False``，绝不把异常抛给用户。

    Args:
        text: 要复制的文本。

    Returns:
        是否复制成功。
    """
    if sys.platform == "win32":
        commands = [["clip"]]
    elif sys.platform == "darwin":
        commands = [["pbcopy"]]
    else:
        commands = [
            ["wl-copy"],
            ["xclip", "-selection", "clipboard"],
            ["xsel", "--clipboard", "--input"],
        ]

    for command in commands:
        try:
            subprocess.run(
                command,
                input=text,
                text=True,
                timeout=5,
                check=True,
            )
            return True
        except Exception:
            continue
    return False


@app.command()
def token(
    ctx: typer.Context,
    show: bool = typer.Option(
        False, "--show", help="直接打印明文（供脚本或无剪贴板环境使用）"
    ),
) -> None:
    """复制管理令牌到剪贴板；加 --show 直接打印明文。"""
    env_file, _plugin_dir = _paths(ctx)

    admin_token = read_env_file(env_file).get("ADMIN_TOKEN") or os.environ.get(
        "ADMIN_TOKEN"
    )
    if not admin_token:
        typer.echo("尚未初始化管理令牌，请先运行 qmin init", err=True)
        raise typer.Exit(1)

    if show:
        typer.echo(admin_token)
        return

    if _copy_to_clipboard(admin_token):
        typer.echo("管理令牌已复制到剪贴板")
        return

    typer.echo("复制到剪贴板失败，请手动复制：")
    typer.echo(admin_token)


def main() -> None:
    """控制台入口。"""
    app()


if __name__ == "__main__":
    main()
