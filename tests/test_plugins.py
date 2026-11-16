"""core/plugins.py 的单元测试。

所有插件都写在 ``tmp_path`` 下，不触碰真实 ``plugins/`` 目录。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from core.events import GroupAtMessage
from core.handlers import router
from core.plugins import iter_plugin_files, load_plugins, set_plugin_enabled
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
