"""插件发现与加载。

插件是 ``plugins/`` 目录下的单个 ``.py`` 文件，文件名即插件名。
加载采用文件路径导入，模块名固定为 ``qmin_plugin_<stem>``，并通过
:func:`core.handlers.plugin_source` 标记处理器来源，便于按插件卸载。

单个插件失败只影响自身：异常被隔离成 :class:`PluginRecord` 中的 ``error``。
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import tempfile
from dataclasses import replace
from pathlib import Path
from types import ModuleType

from core import handlers
from core.handlers import Router, plugin_source
from core.state import PluginRecord, RuntimeState, get_state

# 插件文件后缀。
PLUGIN_SUFFIX = ".py"

# 插件名白名单：小写字母开头，仅允许小写字母 / 数字 / 下划线，最长 64 字符。
PLUGIN_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# 有特殊用途的名字，禁止作为插件名。
RESERVED_PLUGIN_NAMES = frozenset({"__init__", "conftest"})
# 单次安装的源码上限（256 KB），避免误粘贴超大文件。
MAX_PLUGIN_BYTES = 256 * 1024
# 元信息对外展示时的截断长度。
MAX_DISPLAY_NAME = 60
MAX_DESCRIPTION = 200


class PluginValidationError(ValueError):
    """插件名或源码未通过校验（不落盘、不加载）。"""


class PluginExistsError(RuntimeError):
    """同名插件已存在且调用方未要求覆盖。"""


def iter_plugin_files(plugin_dir: Path) -> list[Path]:
    """列出待加载的插件文件。

    Args:
        plugin_dir: 插件目录；不存在时自动创建。

    Returns:
        按文件名排序的 ``.py`` 文件；目录刚创建时为空列表。
        以 ``_`` 开头的文件与目录会被跳过。
    """
    if not plugin_dir.is_dir():
        plugin_dir.mkdir(parents=True, exist_ok=True)
        return []

    files = [
        path
        for path in plugin_dir.glob(f"*{PLUGIN_SUFFIX}")
        if path.is_file() and not path.name.startswith("_")
    ]
    return sorted(files, key=lambda path: path.name)


def _validate_plugin_name(name: str) -> str:
    """校验插件名，返回原名；不合法时抛 :class:`PluginValidationError`。"""
    if (
        not isinstance(name, str)
        or not PLUGIN_NAME_PATTERN.fullmatch(name)
        or name.startswith("_")
        or name in RESERVED_PLUGIN_NAMES
    ):
        raise PluginValidationError(
            "插件名只能由小写字母、数字、下划线组成，且不能以下划线开头"
        )
    return name


def _plugin_path(name: str, plugin_dir: Path) -> Path:
    """校验插件名并返回归属内的目标路径（防路径穿越）。"""
    _validate_plugin_name(name)
    base = plugin_dir.resolve()
    target = (plugin_dir / f"{name}{PLUGIN_SUFFIX}").resolve()
    if target.parent != base:
        raise PluginValidationError("插件路径越界")
    return target


def _validate_plugin_code(name: str, code: str) -> str:
    """校验源码非空、可编码、不超限，并用 ``compile`` 做语法预检。"""
    if not isinstance(code, str) or not code.strip():
        raise PluginValidationError("插件代码不能为空")
    try:
        raw = code.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise PluginValidationError("插件代码必须是合法的 UTF-8 文本") from exc
    if len(raw) > MAX_PLUGIN_BYTES:
        raise PluginValidationError("插件代码过大（上限 256 KB）")
    try:
        compile(code, f"<{name}.py>", "exec")
    except SyntaxError as exc:
        raise PluginValidationError(f"第 {exc.lineno} 行：{exc.msg}") from exc
    return code


def _atomic_write(path: Path, code: str) -> None:
    """先写同目录临时文件再 ``os.replace``，避免半截文件被加载。"""
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(code)
        if os.name == "posix":
            os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _meta_text(value: object, limit: int | None = None) -> str | None:
    """把插件元信息规整成 ``str | None``（非字符串 / 空串一律视为未声明）。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text[:limit] if limit is not None else text


def _read_plugin_meta(module: ModuleType | None) -> tuple[str | None, str | None, str | None]:
    """读取插件元信息；任何异常都退化为 ``None``，不影响加载结果。"""
    if module is None:
        return None, None, None
    try:
        display_name = _meta_text(getattr(module, "__plugin_name__", None), MAX_DISPLAY_NAME)
        description = _meta_text(getattr(module, "__description__", None), MAX_DESCRIPTION)
        version = _meta_text(getattr(module, "__version__", None))
    except Exception:
        return None, None, None
    return display_name, description, version


def _load_plugin_file(path: Path, router: Router) -> PluginRecord:
    """按文件路径加载单个插件，失败时回滚并返回错误记录。

    Notes:
        文件导入本身是同步的（importlib 限制），调用方为启动阶段或管理接口，
        不涉及高频 IO。
    """
    stem = path.stem
    module_name = f"qmin_plugin_{stem}"
    sys.modules.pop(module_name, None)

    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法为 {path.name} 创建导入规格")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        with plugin_source(stem):
            spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        router.unregister_source(stem)
        return PluginRecord(
            name=stem,
            path=str(path),
            enabled=True,
            loaded=False,
            handler_count=0,
            error=f"{type(exc).__name__}: {exc}",
        )

    display_name, description, version = _read_plugin_meta(
        sys.modules.get(module_name)
    )
    return PluginRecord(
        name=stem,
        path=str(path),
        enabled=True,
        loaded=True,
        handler_count=router.count_by_source(stem),
        error=None,
        display_name=display_name,
        description=description,
        version=version,
    )


async def load_plugins(
    plugin_dir: Path,
    *,
    state: RuntimeState | None = None,
    router: Router | None = None,
) -> list[PluginRecord]:
    """加载目录下的全部插件。

    Args:
        plugin_dir: 插件目录；不存在时自动创建。
        state: 运行时状态；为空时使用进程单例。
        router: 事件路由器；为空时使用 ``core.handlers.router``。

    Returns:
        与插件文件一一对应的记录列表（含加载失败的记录）。
    """
    runtime = state if state is not None else get_state()
    target_router = router if router is not None else handlers.router

    records: list[PluginRecord] = []
    for path in iter_plugin_files(plugin_dir):
        record = _load_plugin_file(path, target_router)
        if record.error is not None:
            await runtime.add_log(
                "ERROR", "plugins", f"{record.name} 加载失败: {record.error}"
            )
        records.append(record)

    await runtime.set_plugins(records)
    return records


async def _upsert_state_plugin(state: RuntimeState, record: PluginRecord) -> None:
    """把单条插件记录写回状态（存在则替换，不存在则追加）。"""
    plugins = state.list_plugins()
    for index, existing in enumerate(plugins):
        if existing.name == record.name:
            plugins[index] = record
            break
    else:
        plugins.append(record)
    await state.set_plugins(plugins)


async def set_plugin_enabled(
    name: str,
    enabled: bool,
    *,
    plugin_dir: Path,
    state: RuntimeState | None = None,
    router: Router | None = None,
) -> PluginRecord:
    """启用或禁用单个插件。

    Args:
        name: 插件名（文件名去掉 ``.py``）。
        enabled: ``True`` 启用并重新加载，``False`` 卸载处理器。
        plugin_dir: 插件目录。
        state: 运行时状态；为空时使用进程单例。
        router: 事件路由器；为空时使用 ``core.handlers.router``。

    Returns:
        更新后的插件记录；加载失败时 ``enabled`` 为 ``False`` 且带 ``error``。

    Raises:
        KeyError: 插件不在运行时状态的插件列表中。
    """
    runtime = state if state is not None else get_state()
    target_router = router if router is not None else handlers.router

    if name not in {plugin.name for plugin in runtime.list_plugins()}:
        raise KeyError(name)

    if not enabled:
        # 先切换状态（插件不存在时抛 KeyError，此时不摘处理器），再卸载处理器，
        # 最后把 loaded/handler_count 一并归零，避免面板展示过期的加载状态。
        updated = await runtime.toggle_plugin(name, False)
        target_router.unregister_source(name)
        final = replace(updated, loaded=False, handler_count=0, error=None)
        await _upsert_state_plugin(runtime, final)
        return final

    record = _load_plugin_file(plugin_dir / f"{name}{PLUGIN_SUFFIX}", target_router)
    if record.error is not None:
        await runtime.add_log(
            "ERROR", "plugins", f"{name} 加载失败: {record.error}"
        )
        failed = replace(record, enabled=False)
        await _upsert_state_plugin(runtime, failed)
        return failed

    await runtime.toggle_plugin(name, True)
    loaded = replace(record, enabled=True)
    await _upsert_state_plugin(runtime, loaded)
    return loaded


async def _drop_state_plugin(state: RuntimeState, name: str) -> None:
    """从运行时插件列表中移除指定插件。"""
    remaining = [record for record in state.list_plugins() if record.name != name]
    await state.set_plugins(remaining)


async def install_plugin(
    name: str,
    code: str,
    *,
    plugin_dir: Path,
    overwrite: bool = False,
    router: Router | None = None,
    state: RuntimeState | None = None,
) -> PluginRecord:
    """把粘贴的源码写入插件目录并立即加载。

    Args:
        name: 插件名，同时作为文件名。
        code: 插件源码全文。
        plugin_dir: 插件目录。
        overwrite: 同名文件已存在时是否覆盖。
        router: 处理器注册目标固定为 ``core.handlers`` 的全局 router，
            此参数仅用于卸载与计数。
        state: 运行时状态；为空时使用进程单例。

    Returns:
        安装后的插件记录。加载失败时不抛异常：覆盖安装会回滚到上一版本，
        全新安装会删除文件，两种情况的 ``error`` 都会说明原因。

    Raises:
        PluginValidationError: 插件名或源码不合法（不落盘）。
        PluginExistsError: 同名插件已存在且 ``overwrite`` 为 ``False``。
    """
    runtime = state if state is not None else get_state()
    target_router = router if router is not None else handlers.router

    target = _plugin_path(name, plugin_dir)
    _validate_plugin_code(name, code)

    plugin_dir.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise PluginExistsError(name)

    # 写盘前先备份旧内容，覆盖安装失败时用它回滚。
    old_code = target.read_text(encoding="utf-8") if target.exists() else None

    # 覆盖安装前必须先摘掉旧处理器，否则新模块再注册一次会让处理器翻倍。
    target_router.unregister_source(name)
    _atomic_write(target, code)

    record = _load_plugin_file(target, target_router)
    if record.error is not None:
        failure = record.error
        if old_code is not None:
            # 覆盖安装失败：把上一版本写回并重新加载，避免用户永久失去插件。
            _atomic_write(target, old_code)
            restored = _load_plugin_file(target, target_router)
            await _upsert_state_plugin(runtime, restored)
            await runtime.add_log(
                "ERROR", "plugins", f"{name} 安装失败，已回滚：{failure}"
            )
            return replace(
                record,
                error=f"新代码加载失败，已回滚到上一版本：{failure}",
            )
        # 全新安装失败：删掉文件且不留幽灵记录，错误由接口响应返回。
        try:
            target.unlink()
        except OSError:
            pass
        await _drop_state_plugin(runtime, name)
        await runtime.add_log("ERROR", "plugins", f"{name} 安装失败：{failure}")
        return record

    await _upsert_state_plugin(runtime, record)
    await runtime.add_log("INFO", "plugins", f"插件已安装：{name}")
    return record


async def remove_plugin(
    name: str,
    *,
    plugin_dir: Path,
    router: Router | None = None,
    state: RuntimeState | None = None,
) -> None:
    """删除插件文件并摘除其处理器。

    Raises:
        PluginValidationError: 插件名不合法。
        KeyError: 插件文件不存在。
    """
    runtime = state if state is not None else get_state()
    target_router = router if router is not None else handlers.router

    target = _plugin_path(name, plugin_dir)
    if not target.is_file():
        raise KeyError(name)

    target_router.unregister_source(name)
    await _drop_state_plugin(runtime, name)
    try:
        target.unlink()
    except FileNotFoundError:
        raise KeyError(name) from None
    sys.modules.pop(f"qmin_plugin_{name}", None)
    await runtime.add_log("INFO", "plugins", f"插件已移除：{name}")


async def reload_plugin(
    name: str,
    *,
    plugin_dir: Path,
    router: Router | None = None,
    state: RuntimeState | None = None,
) -> PluginRecord:
    """重新加载磁盘上的插件文件（用于手工改完代码后热更新）。

    Raises:
        PluginValidationError: 插件名不合法。
        KeyError: 插件文件不存在。
    """
    runtime = state if state is not None else get_state()
    target_router = router if router is not None else handlers.router

    target = _plugin_path(name, plugin_dir)
    if not target.is_file():
        raise KeyError(name)

    # 先摘处理器再重新加载，保证重新加载后不会出现重复回复。
    target_router.unregister_source(name)
    record = _load_plugin_file(target, target_router)
    if record.error is not None:
        await runtime.add_log(
            "ERROR", "plugins", f"{name} 加载失败: {record.error}"
        )
    else:
        await runtime.add_log("INFO", "plugins", f"插件已重新加载：{name}")
    await _upsert_state_plugin(runtime, record)
    return record
