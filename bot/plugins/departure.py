"""/departure on|off — per-chat toggle for the farewell handler.

Default is ON. Use this when a group wants the bot's leave messages
silenced without also turning off welcome cards (which the /greetings
toggle controls).
"""

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode

from bot.utils import emoji as e
from bot.utils.departure import is_enabled, set_enabled

_HTML = ParseMode.HTML

_ADMIN_STATUSES = (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


async def _is_admin(client, chat_id, user_id) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in _ADMIN_STATUSES


@Client.on_message(filters.command(["departure", "farewell", "departures"]))
async def departure_command(client, message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            f"{e.PEOPLE} <b>Groups only</b>\n"
            "<i>/departure works inside a group.</i>", parse_mode=_HTML)
        return

    if not message.from_user or not await _is_admin(
        client, message.chat.id, message.from_user.id
    ):
        await message.reply_text(
            "🔒 <b>Admins only</b>\n"
            "<i>Only group admins can toggle departures.</i>", parse_mode=_HTML)
        return

    if len(message.command) < 2:
        state = "ON ✅" if is_enabled(message.chat.id) else "OFF ❌"
        await message.reply_text(
            f"{e.WAVE} <b>Departure messages:</b> {state}\n"
            "<i>Use</i> <code>/departure on</code> <i>or</i> <code>/departure off</code>.",
            parse_mode=_HTML)
        return

    arg = message.command[1].lower()
    if arg in ("on", "enable", "enabled", "yes", "true"):
        set_enabled(message.chat.id, True)
        await message.reply_text(
            f"✅ {e.WAVE} <b>Departures ON</b>\n"
            "<i>I'll wave goodbye when members leave.</i>", parse_mode=_HTML)
    elif arg in ("off", "disable", "disabled", "no", "false"):
        set_enabled(message.chat.id, False)
        await message.reply_text(
            f"❌ {e.WAVE} <b>Departures OFF</b>\n"
            "<i>I'll stay quiet when members leave.</i>", parse_mode=_HTML)
    else:
        await message.reply_text(
            "<i>Use</i> <code>/departure on</code> <i>or</i> <code>/departure off</code>.",
            parse_mode=_HTML)
