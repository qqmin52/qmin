"""示例插件：收到包含“你好”的群 @ 消息时回复。"""

from core.handlers import on_group_at


@on_group_at("你好")
async def hello(event) -> None:
    """回复固定文案。"""
    await event.reply("你好呀")
