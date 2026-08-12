from pyrogram import Client, filters
from pyrogram.enums import ChatType

from bot.utils import queue as q
from bot.utils.playback import end_session


@Client.on_message(filters.command(["stop", "end"]))
async def stop_command(client, message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text("👥 /stop only works in groups.")
        return

    was_active = q.is_active(message.chat.id)
    if not was_active:
        # Even if nothing is playing, drop any stale queue + try to leave
        # in case the assistant lingered after a previous crash.
        q.clear(message.chat.id)
        await message.reply_text("ℹ️ Nothing was playing.")
        return

    await end_session(message.chat.id)
    await message.reply_text(
        "⏹️ Playback stopped and queue cleared. The assistant left the voice "
        "chat but stays in the group, so /play starts again instantly."
    )
