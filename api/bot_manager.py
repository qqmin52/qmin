"""BotManager：在管理面板进程里按请求启动 / 停止 QminBot。

不持有 AppID / AppSecret 快照——每次 start 都重新从 ``env_file`` 读取最新凭证。
因此面板里「保存 Secret → 点启动」无需重启进程就能用新凭证连上。

只调 ``QminBot.start`` / ``QminBot.stop``，不 import botpy 直接操作 SDK，
因此可以安全地由测试替换 ``QminBot`` 类（monkeypatch ``api.bot_manager.QminBot``）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from core.bot import QminBot
from core.config import ConfigError, load_settings
from core.state import RuntimeState


class BotManager:
    """Bot 生命周期管理，提供启动 / 停止 / 查询能力。

    构造：
        manager = BotManager(env_file=Path(".env"), state=get_state())

    用法：
        await manager.start()     # 返回 {started, error}
        await manager.stop()
        manager.running           # bool

    Notes:
        - start 每次都从 ``env_file`` load_settings；ConfigError（未配置）时
          返回 started=False 且 error 指向设置页引导用户去填写。
        - start 后给 5 秒窗口判断是否立刻抛异常，便于 UI 即时反馈登录失败。
        - stop 会 cancel 任务并吞掉 CancelledError，保证幂等。
    """

    _START_WINDOW = 5.0

    def __init__(
        self,
        *,
        env_file: Path,
        state: RuntimeState,
    ) -> None:
        self._env_file = env_file
        self._state = state
        self._bot: QminBot | None = None
        self._task: asyncio.Task[Any] | None = None
        self._lock = asyncio.Lock()
        self._started_at: float | None = None

    # ---------- 对外接口 ----------

    @property
    def running(self) -> bool:
        """当前 Bot 任务是否正在运行。"""
        return self._task is not None and not self._task.done()

    def _on_task_done(self, task: asyncio.Task[Any]) -> None:
        """后台任务完成回调：仅捕获 start() 未处理的异常，写一条 ERROR 日志。

        start() 里对 5 秒窗口内立即抛的异常已经做了显式处理并返回
        started=False + 日志；这里用时间窗口判定——若 task 完成时距离
        create_task 还不到 ``_START_WINDOW``，说明是 start() 自己要处理的
        立即失败路径，直接 return；否则判定为长尾崩溃，写日志。
        """
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        # stop() 已接管（self._task 已被置 None 或指向别的）
        if self._task is not task:
            return

        # 时间窗口判定：窗口内完成 → start() 自己会记"启动失败"，这里不重复。
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        now = loop.time()
        started = self._started_at if self._started_at is not None else now
        if now - started < self._START_WINDOW:
            return

        async def _log() -> None:
            await self._state.add_log(
                "ERROR",
                "bot",
                f"机器人异常退出：{type(exc).__name__}: {exc}",
            )

        asyncio.create_task(_log())

    async def start(self) -> dict[str, bool | str | None]:
        """启动 Bot，返回结果字典。

        Returns:
            ``{"started": True, "error": None}`` 或
            ``{"started": False, "error": "类型名: 消息"}``。
            凭证缺失时 error 为中文引导文本（"凭证未配置，请先在设置页填写 AppID / AppSecret"）。
        """
        async with self._lock:
            if self.running:
                return {"started": True, "error": None}

            # 每次 start 都重新从 .env 读——面板改 Secret 后点启动立即生效。
            try:
                settings = load_settings(self._env_file)
            except ConfigError as exc:
                # 凭证缺失（面板未完成初始配置）：不构造 QminBot，直接拒绝。
                missing = getattr(exc, "missing", [])
                display = "、".join(missing) if missing else "必填项"
                err = (
                    f"配置不完整，缺少：{display}。"
                    "请在设置页补全后再启动"
                )
                return {"started": False, "error": err}

            self._bot = QminBot(
                app_id=settings.app_id,
                app_secret=settings.app_secret.get_secret_value(),
                state=self._state,
            )
            # shield 防止 waiter 取消时连同 bot 任务一起被取消
            self._task = asyncio.create_task(self._bot.start())
            self._task.add_done_callback(self._on_task_done)
            self._started_at = asyncio.get_running_loop().time()
            try:
                _done, _pending = await asyncio.wait(
                    (self._task,), timeout=self._START_WINDOW
                )
            except asyncio.CancelledError:
                # BotManager 自身被取消（罕见），透传
                raise

            if self._task.done():
                exc = self._task.exception()
                if exc is not None:
                    self._task = None
                    await self._state.add_log(
                        "ERROR",
                        "bot",
                        f"机器人启动失败：{type(exc).__name__}: {exc}",
                    )
                    return {
                        "started": False,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                # 5 秒内正常完成（极少数场景），视为成功
                self._task = None
                return {"started": True, "error": None}

            # 窗口内未抛异常，判定启动成功；后台继续运行
            return {"started": True, "error": None}

    async def stop(self) -> dict[str, bool | str | None]:
        """停止 Bot，返回 ``{"started": False, "error": None}``。"""
        async with self._lock:
            task = self._task
            self._task = None
            self._started_at = None

            if task is None:
                return {"started": False, "error": None}

            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            if self._bot is not None:
                try:
                    await self._bot.stop()
                except asyncio.CancelledError:
                    pass
                except Exception:
                    # stop 失败只记录，不影响返回
                    pass
                self._bot = None

            return {"started": False, "error": None}
