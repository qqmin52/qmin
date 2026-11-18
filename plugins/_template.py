"""插件模板：复制本文件并改名为自己的插件即可开始。

注意：以 ``_`` 开头的文件不会被当作插件加载（本文件就是模板，不参与运行）。

使用方式：
1. 复制为 ``plugins/my_plugin.py``（文件名只能用小写字母、数字、下划线）
2. 改下面的关键字与回复内容
3. 在面板「插件」页点「重新加载」；或直接把代码粘贴到「安装插件」对话框里

更多说明见 docs/PLUGINS.md。
"""

from core.handlers import on_group_at

# 可选元信息：面板会展示，不写也不影响加载
__plugin_name__ = "插件模板"
__description__ = "收到包含 hello 的群消息时回复一句问候"
__version__ = "0.1.0"


# on_group_at 按子串匹配正文；不传参数表示匹配所有群 @ 消息。
@on_group_at("hello")
async def hello(event) -> None:
    """最小处理器：还原一句文本。

    event 可用字段与方法：
      group_openid / content / sender_id / sender_name / msg_id / timestamp / raw
      await event.reply("文本")
    """
    who = event.sender_name or event.sender_id[:8]
    await event.reply(f"hello，{who}")
