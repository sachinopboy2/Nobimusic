import html

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType, MessageEntityType, ParseMode

from bot.client import userbot
from bot.utils import emoji as e

_HTML = ParseMode.HTML


_ADMIN_STATUSES = (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


async def _is_admin(client, chat_id, user_id) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in _ADMIN_STATUSES


async def _resolve_target(client, message):
    """Return (target_user, leftover_args_as_reason). target_user is a User object."""
    text = message.text or ""

    # Text-mention entities — tags of usernameless users carry the User object.
    for ent in (message.entities or []):
        if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
            mention_text = text[ent.offset:ent.offset + ent.length]
            after_cmd = text.split(maxsplit=1)
            after_cmd = after_cmd[1] if len(after_cmd) > 1 else ""
            reason = after_cmd.replace(mention_text, "", 1).strip()
            return ent.user, reason

    reply = message.reply_to_message
    if reply and reply.from_user:
        reason = " ".join(message.command[1:]).strip()
        return reply.from_user, reason

    if len(message.command) < 2:
        return None, ""

    raw = message.command[1].lstrip("@")
    reason = " ".join(message.command[2:]).strip()

    # Bot accounts can't always resolve @username; the userbot (MTProto) can.
    try:
        if raw.isdigit():
            user = await client.get_users(int(raw))
        else:
            try:
                user = await userbot.get_users(raw)
            except Exception:
                user = await client.get_users(raw)
        return user, reason
    except Exception:
        return None, reason


@Client.on_message(filters.command("ban"))
async def ban_command(client, message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            f"{e.PEOPLE} <b>Groups only</b>\n"
            "<i>/ban works inside a group.</i>", parse_mode=_HTML)
        return

    if not await _is_admin(client, message.chat.id, message.from_user.id):
        await message.reply_text(
            "🔒 <b>Admins only</b>\n"
            "<i>Only group admins can /ban.</i>", parse_mode=_HTML)
        return

    me = await client.get_me()
    if not await _is_admin(client, message.chat.id, me.id):
        await message.reply_text(
            f"⚠️ {e.SHIELD} <b>I need permission</b>\n"
            "<i>Make me an admin with <b>Ban Users</b> rights first.</i>",
            parse_mode=_HTML)
        return

    target, reason = await _resolve_target(client, message)
    if target is None:
        await message.reply_text(
            f"{e.SHIELD} <b>Ban — how to use</b>\n"
            "• <i>Reply to a message with</i> <code>/ban [reason]</code>\n"
            "• <code>/ban &lt;user_id&gt; [reason]</code>\n"
            "• <code>/ban @username [reason]</code>", parse_mode=_HTML)
        return

    if target.id == me.id:
        await message.reply_text("🙃 <b>I'm not going to ban myself.</b>", parse_mode=_HTML)
        return
    if target.id == message.from_user.id:
        await message.reply_text("🙃 <b>You can't ban yourself.</b>", parse_mode=_HTML)
        return
    if await _is_admin(client, message.chat.id, target.id):
        await message.reply_text("🔒 <b>I can't ban another admin.</b>", parse_mode=_HTML)
        return

    try:
        await client.ban_chat_member(message.chat.id, target.id)
    except Exception as exc:
        await message.reply_text(
            "❌ <b>Ban failed</b>\n"
            f"<code>{html.escape(str(exc))}</code>", parse_mode=_HTML)
        return

    text = (
        f"{e.SHIELD} <b>Banned</b> 🚫\n"
        f"<b>User:</b> {e.mention(target)}\n"
        f"<b>By:</b> {e.mention(message.from_user)}"
    )
    if reason:
        text += f"\n<b>Reason:</b> {html.escape(reason)}"
    await message.reply_text(text, parse_mode=_HTML)
