"""命令行入口：``qmin init`` / ``qmin doctor`` / ``qmin run``。

对应 ``pyproject.toml`` 中的 ``qmin = "core.cli:main"``。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
import uvicorn

from api.main import create_app
from core.bot import QminBot
from core.config import ConfigError, ensure_admin_token, load_settings, write_env_file
from core.plugins import iter_plugin_files, load_plugins

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

    write_env_file(
        env_file,
        {
            "APP_ID": app_id,
            "APP_SECRET": app_secret,
            "HOST": host,
            "PORT": port,
            "LOG_LEVEL": log_level,
        },
    )
    ensure_admin_token(env_file)

    typer.echo("下一步：执行 `qmin doctor` 检查配置，再执行 `qmin run` 启动机器人。")


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
def run(ctx: typer.Context) -> None:
    """加载插件，同时启动机器人与管理 API。"""
    env_file, plugin_dir = _paths(ctx)

    ensure_admin_token(env_file)
    try:
        settings = load_settings(env_file)
    except ConfigError as exc:
        typer.echo(exc.hint, err=True)
        raise typer.Exit(1) from None

    typer.echo(f"管理面板: http://{settings.host}:{settings.port}")

    async def _serve() -> None:
        await load_plugins(plugin_dir)
        bot = QminBot(
            app_id=settings.app_id,
            app_secret=settings.app_secret.get_secret_value(),
        )
        api_app = create_app(settings=settings, plugin_dir=plugin_dir)
        config = uvicorn.Config(
            api_app,
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level.lower(),
            lifespan="off",
        )
        server = uvicorn.Server(config)
        api_task = asyncio.create_task(server.serve())
        try:
            await bot.start()
        finally:
            server.should_exit = True
            await api_task
            await bot.stop()

    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        typer.echo("已停止")
        raise typer.Exit(0) from None


@app.command()
def api(ctx: typer.Context) -> None:
    """只启动管理面板，不连接 QQ（不会占用机器人登录）。"""
    env_file, plugin_dir = _paths(ctx)

    ensure_admin_token(env_file)
    try:
        settings = load_settings(env_file)
    except ConfigError as exc:
        typer.echo(exc.hint, err=True)
        raise typer.Exit(1) from None

    typer.echo(f"管理面板: http://{settings.host}:{settings.port}")

    async def _prepare() -> object:
        """加载插件并构建管理面板应用（让面板能看到插件状态）。"""
        await load_plugins(plugin_dir)
        return create_app(settings=settings, plugin_dir=plugin_dir)

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


def main() -> None:
    """控制台入口。"""
    app()


if __name__ == "__main__":
    main()
