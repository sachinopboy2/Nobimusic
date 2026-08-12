from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode

from bot.utils import emoji as e
from bot.utils.greetings import is_enabled, set_enabled

_HTML = ParseMode.HTML

_ADMIN_STATUSES = (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


async def _is_admin(client, chat_id, user_id) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in _ADMIN_STATUSES


@Client.on_message(filters.command("greetings"))
async def greetings_command(client, message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            f"{e.PEOPLE} <b>Groups only</b>\n"
            "<i>/greetings works inside a group.</i>", parse_mode=_HTML)
        return

    if not await _is_admin(client, message.chat.id, message.from_user.id):
        await message.reply_text(
            "🔒 <b>Admins only</b>\n"
            "<i>Only group admins can toggle greetings.</i>", parse_mode=_HTML)
        return

    if len(message.command) < 2:
        state = "ON ✅" if is_enabled(message.chat.id) else "OFF ❌"
        await message.reply_text(
            f"{e.WAVE} <b>Greetings:</b> {state}\n"
            "<i>Use</i> <code>/greetings on</code> <i>or</i> <code>/greetings off</code>.",
            parse_mode=_HTML)
        return

    arg = message.command[1].lower()
    if arg in ("on", "enable", "enabled", "yes", "true"):
        set_enabled(message.chat.id, True)
        await message.reply_text(
            f"✅ {e.WAVE} <b>Greetings ON</b>\n"
            "<i>New members will be welcomed.</i>", parse_mode=_HTML)
    elif arg in ("off", "disable", "disabled", "no", "false"):
        set_enabled(message.chat.id, False)
        await message.reply_text(
            f"❌ {e.WAVE} <b>Greetings OFF</b>\n"
            "<i>New members won't be welcomed.</i>", parse_mode=_HTML)
    else:
        await message.reply_text(
            "<i>Use</i> <code>/greetings on</code> <i>or</i> <code>/greetings off</code>.",
            parse_mode=_HTML)
