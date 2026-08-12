import html

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode

from bot.utils import emoji as e
from bot.utils import queue as q
from bot.utils.music import music

_HTML = ParseMode.HTML


@Client.on_message(filters.command("resume"))
async def resume_command(client, message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            f"{e.PEOPLE} <b>Groups only</b>\n"
            "<i>/resume works inside a group voice chat.</i>", parse_mode=_HTML)
        return

    if not q.is_active(message.chat.id):
        await message.reply_text(
            f"{e.WAND} <b>Nothing is paused</b>\n"
            "<i>Use /play to start a song.</i>", parse_mode=_HTML)
        return

    try:
        await music.resume(message.chat.id)
    except Exception as exc:
        await message.reply_text(
            f"{e.WARNING} <b>Resume failed</b>\n"
            f"<code>{html.escape(f'{type(exc).__name__}: {exc}')}</code>",
            parse_mode=_HTML)
        return

    await message.reply_text(
        f"{e.MUSIC} <b>Resumed</b> {e.HEAD}", parse_mode=_HTML)
