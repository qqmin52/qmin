"""core/plugins.py 的单元测试。

所有插件都写在 ``tmp_path`` 下，不触碰真实 ``plugins/`` 目录。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.events import GroupAtMessage
from core.handlers import router
from core.plugins import (
    PluginExistsError,
    PluginValidationError,
    install_plugin,
    iter_plugin_files,
    load_plugins,
    reload_plugin,
    remove_plugin,
    set_plugin_enabled,
)
from core.state import get_state, reset_state

HANDLER_PLUGIN = """
from core.handlers import on_group_at


@on_group_at()
async def handler(event):
    return None
"""


async def _noop_replier(content: str) -> Any:
    return {"ok": True}


def make_event(content: str = "任意内容") -> GroupAtMessage:
    """构造最小可用的群 @ 事件。"""
    return GroupAtMessage(
        group_openid="group-1",
        content=content,
        sender_id="user-1",
        sender_name="小明",
        msg_id="msg-1",
        timestamp=None,
        raw={},
        _replier=_noop_replier,
    )


def write_plugin(plugin_dir: Path, stem: str, body: str) -> Path:
    """写入一个插件文件并返回路径。"""
    path = plugin_dir / f"{stem}.py"
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def clean_state() -> None:
    """每个用例前后清理状态与路由表。"""
    reset_state()
    router.clear()
    yield
    router.clear()
    reset_state()


async def test_load_plugins_registers_handler(tmp_path: Path) -> None:
    """正常插件被加载，记录正确且处理器已注册。"""
    write_plugin(tmp_path, "demo", HANDLER_PLUGIN)

    records = await load_plugins(tmp_path)

    assert len(records) == 1
    assert records[0].name == "demo"
    assert records[0].loaded is True
    assert records[0].handler_count == 1
    assert records[0].error is None
    assert router.count_by_source("demo") == 1


async def test_plugin_exception_is_isolated(tmp_path: Path) -> None:
    """模块级抛异常的插件不会中断加载，处理器被回滚。"""
    write_plugin(tmp_path, "broken", "raise RuntimeError('boom')\n")

    records = await load_plugins(tmp_path)

    assert len(records) == 1
    assert records[0].loaded is False
    assert records[0].handler_count == 0
    assert records[0].error is not None
    assert "RuntimeError" in records[0].error
    assert router.count_by_source("broken") == 0


async def test_broken_plugin_does_not_affect_good_one(tmp_path: Path) -> None:
    """同时存在正常与异常插件时，正常插件不受影响。"""
    write_plugin(tmp_path, "good", HANDLER_PLUGIN)
    write_plugin(tmp_path, "bad", "raise ValueError('bad plugin')\n")

    records = await load_plugins(tmp_path)

    by_name = {record.name: record for record in records}
    assert by_name["good"].loaded is True
    assert by_name["good"].handler_count == 1
    assert by_name["bad"].loaded is False
    assert router.count_by_source("good") == 1
    assert router.count_by_source("bad") == 0


async def test_disable_then_enable_plugin(tmp_path: Path) -> None:
    """禁用后不再命中，重新启用后再次命中。"""
    write_plugin(tmp_path, "demo", HANDLER_PLUGIN)
    await load_plugins(tmp_path)
    assert await router.dispatch(make_event()) == 1

    disabled = await set_plugin_enabled("demo", False, plugin_dir=tmp_path)

    assert disabled.enabled is False
    assert await router.dispatch(make_event()) == 0

    enabled = await set_plugin_enabled("demo", True, plugin_dir=tmp_path)

    assert enabled.enabled is True
    assert enabled.loaded is True
    assert enabled.handler_count == 1
    assert await router.dispatch(make_event()) == 1


async def test_disable_clears_loaded_and_handler_count(tmp_path: Path) -> None:
    """禁用插件后 loaded 与 handler_count 归零，重新启用后恢复。"""
    write_plugin(tmp_path, "demo", HANDLER_PLUGIN)
    await load_plugins(tmp_path)

    disabled = await set_plugin_enabled("demo", False, plugin_dir=tmp_path)

    assert disabled.enabled is False
    assert disabled.loaded is False
    assert disabled.handler_count == 0
    assert disabled.error is None
    assert router.count_by_source("demo") == 0

    enabled = await set_plugin_enabled("demo", True, plugin_dir=tmp_path)

    assert enabled.enabled is True
    assert enabled.loaded is True
    assert enabled.handler_count == 1


async def test_missing_directory_is_created(tmp_path: Path) -> None:
    """目录不存在时自动创建并返回空列表。"""
    target = tmp_path / "plugins_missing"

    records = await load_plugins(target)

    assert records == []
    assert target.is_dir()


async def test_private_files_are_skipped(tmp_path: Path) -> None:
    """以 _ 开头的文件不参与加载。"""
    write_plugin(tmp_path, "_private", "raise RuntimeError('不应被加载')\n")

    files = iter_plugin_files(tmp_path)
    records = await load_plugins(tmp_path)

    assert files == []
    assert records == []


async def test_toggle_unknown_plugin_raises_key_error(tmp_path: Path) -> None:
    """对未登记的插件切换开关抛 KeyError。"""
    with pytest.raises(KeyError):
        await set_plugin_enabled("ghost", True, plugin_dir=tmp_path)


# ---------------------------------------------------------------- 面板内安装


async def test_install_plugin_success(tmp_path: Path) -> None:
    """安装成功后文件落盘、record 已加载且处理器只有一条。"""
    record = await install_plugin("hello", HANDLER_PLUGIN, plugin_dir=tmp_path)

    assert (tmp_path / "hello.py").is_file()
    assert record.loaded is True
    assert record.handler_count == 1
    assert record.error is None
    assert router.count_by_source("hello") == 1
    assert [item.name for item in get_state().list_plugins()] == ["hello"]


@pytest.mark.parametrize("bad_name", ["../evil", "a/b", "_hidden", "Hello", ""])
async def test_install_plugin_rejects_invalid_name(
    tmp_path: Path, bad_name: str
) -> None:
    """非法插件名一律抛 PluginValidationError，且目录里不落任何文件。"""
    with pytest.raises(PluginValidationError):
        await install_plugin(bad_name, HANDLER_PLUGIN, plugin_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


async def test_install_plugin_rejects_syntax_error(tmp_path: Path) -> None:
    """语法错误在预检阶段被拦下，错误信息含行号，且不落盘。"""
    with pytest.raises(PluginValidationError) as excinfo:
        await install_plugin("broken", "def broken(:\n    pass\n", plugin_dir=tmp_path)

    assert "第 1 行" in str(excinfo.value)
    assert list(tmp_path.iterdir()) == []


async def test_install_plugin_existing_without_overwrite(tmp_path: Path) -> None:
    """同名插件已存在且未要求覆盖时抛 PluginExistsError。"""
    await install_plugin("demo", HANDLER_PLUGIN, plugin_dir=tmp_path)

    with pytest.raises(PluginExistsError):
        await install_plugin("demo", HANDLER_PLUGIN, plugin_dir=tmp_path)


async def test_install_plugin_overwrite_keeps_single_handler(tmp_path: Path) -> None:
    """覆盖安装不会让处理器翻倍。"""
    await install_plugin("demo", HANDLER_PLUGIN, plugin_dir=tmp_path)

    record = await install_plugin(
        "demo",
        HANDLER_PLUGIN.replace("return None", "return 1"),
        plugin_dir=tmp_path,
        overwrite=True,
    )

    assert record.handler_count == 1
    assert router.count_by_source("demo") == 1
    assert await router.dispatch(make_event()) == 1


async def test_install_plugin_failure_rolls_back_file(tmp_path: Path) -> None:
    """加载期异常不抛给调用方：删除刚写入的文件，但保留失败记录。"""
    record = await install_plugin(
        "boom", "raise RuntimeError('boom')\n", plugin_dir=tmp_path
    )

    assert record.loaded is False
    assert record.error is not None
    assert "RuntimeError" in record.error
    assert not (tmp_path / "boom.py").exists()
    assert list(tmp_path.glob("*.py")) == []
    assert [path.name for path in tmp_path.glob("*.tmp")] == []
    # 全新安装失败不留幽灵记录，错误只通过返回值/接口响应告知。
    assert get_state().list_plugins() == []


async def test_overwrite_failure_restores_previous_version(tmp_path: Path) -> None:
    """坏代码覆盖好插件时回滚到上一版本，插件仍能正常响应。"""
    good_code = HANDLER_PLUGIN
    await install_plugin("demo", good_code, plugin_dir=tmp_path)

    record = await install_plugin(
        "demo",
        "raise RuntimeError('bad version')\n",
        plugin_dir=tmp_path,
        overwrite=True,
    )

    assert (tmp_path / "demo.py").read_text(encoding="utf-8") == good_code
    assert record.error is not None
    assert "已回滚" in record.error
    assert router.count_by_source("demo") == 1
    assert await router.dispatch(make_event()) == 1

    records = get_state().list_plugins()
    assert len(records) == 1
    assert records[0].name == "demo"
    assert records[0].loaded is True
    assert records[0].handler_count == 1


async def test_install_plugin_reads_metadata(tmp_path: Path) -> None:
    """安装时读取 __plugin_name__ / __description__ / __version__。"""
    body = (
        '__plugin_name__ = "演示插件"\n'
        '__description__ = "用于测试的插件"\n'
        '__version__ = "1.2.3"\n' + HANDLER_PLUGIN
    )

    record = await install_plugin("demo", body, plugin_dir=tmp_path)

    assert record.display_name == "演示插件"
    assert record.description == "用于测试的插件"
    assert record.version == "1.2.3"


async def test_load_plugins_truncates_metadata(tmp_path: Path) -> None:
    """元信息超长时按 60 / 200 字符截断，非字符串视为未声明。"""
    body = (
        '__plugin_name__ = "' + "名" * 80 + '"\n'
        '__description__ = "' + "述" * 300 + '"\n'
        "__version__ = 123\n"
    ) + HANDLER_PLUGIN
    write_plugin(tmp_path, "long_meta", body)

    records = await load_plugins(tmp_path)

    assert records[0].display_name is not None
    assert len(records[0].display_name) == 60
    assert records[0].description is not None
    assert len(records[0].description) == 200
    assert records[0].version is None


async def test_reload_plugin_keeps_single_handler(tmp_path: Path) -> None:
    """重新加载不会让处理器翻倍。"""
    await install_plugin("demo", HANDLER_PLUGIN, plugin_dir=tmp_path)

    record = await reload_plugin("demo", plugin_dir=tmp_path)

    assert record.loaded is True
    assert record.handler_count == 1
    assert router.count_by_source("demo") == 1
    assert await router.dispatch(make_event()) == 1


async def test_remove_plugin_cleans_file_and_state(tmp_path: Path) -> None:
    """删除插件后文件消失、处理器归零、状态列表移除。"""
    await install_plugin("demo", HANDLER_PLUGIN, plugin_dir=tmp_path)

    await remove_plugin("demo", plugin_dir=tmp_path)

    assert not (tmp_path / "demo.py").exists()
    assert router.count_by_source("demo") == 0
    assert get_state().list_plugins() == []
    assert await router.dispatch(make_event()) == 0


async def test_remove_unknown_plugin_raises_key_error(tmp_path: Path) -> None:
    """删除不存在的插件抛 KeyError。"""
    with pytest.raises(KeyError):
        await remove_plugin("ghost", plugin_dir=tmp_path)
