from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode

from bot.utils import emoji as e
from bot.utils import queue as q
from bot.utils.playback import clear_queue

_HTML = ParseMode.HTML


@Client.on_message(filters.command(["clearqueue", "cq", "clearall"]))
async def clearqueue_command(client, message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            f"{e.PEOPLE} <b>Groups only</b>\n"
            "<i>/clearqueue works inside a group voice chat.</i>", parse_mode=_HTML)
        return

    had = q.is_active(message.chat.id) or bool(q.upcoming(message.chat.id))
    await clear_queue(message.chat.id)
    if had:
        await message.reply_text(
            f"🗑️ {e.MUSIC} <b>Queue cleared</b>\n"
            "<i>Playback stopped.</i>", parse_mode=_HTML)
    else:
        await message.reply_text(
            f"{e.WAND} <b>Queue already empty</b>", parse_mode=_HTML)
