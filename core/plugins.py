"""插件发现与加载。

插件是 ``plugins/`` 目录下的单个 ``.py`` 文件，文件名即插件名。
加载采用文件路径导入，模块名固定为 ``qmin_plugin_<stem>``，并通过
:func:`core.handlers.plugin_source` 标记处理器来源，便于按插件卸载。

单个插件失败只影响自身：异常被隔离成 :class:`PluginRecord` 中的 ``error``。
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import replace
from pathlib import Path

from core import handlers
from core.handlers import Router, plugin_source
from core.state import PluginRecord, RuntimeState, get_state

# 插件文件后缀。
PLUGIN_SUFFIX = ".py"


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

    return PluginRecord(
        name=stem,
        path=str(path),
        enabled=True,
        loaded=True,
        handler_count=router.count_by_source(stem),
        error=None,
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
