import html

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode

from bot.utils import emoji as e
from bot.utils import queue as q
from bot.utils.music import music

_HTML = ParseMode.HTML


@Client.on_message(filters.command("pause"))
async def pause_command(client, message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            f"{e.PEOPLE} <b>Groups only</b>\n"
            "<i>/pause works inside a group voice chat.</i>", parse_mode=_HTML)
        return

    if not q.is_active(message.chat.id):
        await message.reply_text(
            f"{e.WAND} <b>Nothing is playing</b>\n"
            "<i>Start something with /play.</i>", parse_mode=_HTML)
        return

    try:
        await music.pause(message.chat.id)
    except Exception as exc:
        await message.reply_text(
            "❌ <b>Pause failed</b>\n"
            f"<code>{html.escape(f'{type(exc).__name__}: {exc}')}</code>",
            parse_mode=_HTML)
        return

    await message.reply_text(
        f"⏸️ {e.HEAD} <b>Paused</b>\n<i>Use /resume to continue.</i>",
        parse_mode=_HTML)
