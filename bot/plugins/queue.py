import html

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode

from bot.utils import emoji as e
from bot.utils import queue as q

_HTML = ParseMode.HTML

# How many upcoming tracks to render in the message. Telegram's 4096-char
# limit makes a full render risky for long playlists; truncate and tell
# the user how many more are pending.
_MAX_RENDER = 15


def _line(chat_id: int, idx: int, track: q.Track) -> str:
    icon = "🎬" if track.is_video else "🎵"
    return (f"<b>{idx}.</b> {icon} {html.escape(q.display_title(chat_id, track))} "
            f"— <i>{html.escape(str(track.requested_by))}</i>")


@Client.on_message(filters.command("queue"))
async def queue_command(client, message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            f"{e.PEOPLE} <b>Groups only</b>\n"
            "<i>/queue works inside a group voice chat.</i>", parse_mode=_HTML)
        return

    current = q.now_playing(message.chat.id)
    upcoming = q.upcoming(message.chat.id)

    if not current and not upcoming:
        await message.reply_text(
            f"{e.MUSIC} <b>Queue is empty</b>\n"
            "<i>Use</i> <code>/play &lt;song&gt;</code> <i>to add music.</i>",
            parse_mode=_HTML)
        return

    lines = [f"{e.MUSIC} <b>Queue</b>"]
    if current:
        icon = "🎬" if current.is_video else "🎵"
        lines.append(
            f"\n▶️ <b>Now playing:</b> {icon} "
            f"{html.escape(q.display_title(message.chat.id, current))} "
            f"— <i>{html.escape(str(current.requested_by))}</i>"
        )
    if upcoming:
        lines.append("\n⏭️ <b>Up next:</b>")
        for i, track in enumerate(upcoming[:_MAX_RENDER], start=1):
            lines.append(_line(message.chat.id, i, track))
        extra = len(upcoming) - _MAX_RENDER
        if extra > 0:
            lines.append(f"<i>… and {extra} more.</i>")
    else:
        lines.append("\n<i>(nothing else in the queue)</i>")

    await message.reply_text("\n".join(lines), parse_mode=_HTML)
