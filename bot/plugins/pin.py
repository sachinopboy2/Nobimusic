"""/pin, /unpin, /unpinall — message pinning for group admins.

Structural pattern mirrors bot/plugins/ban.py:
  chat-type check → caller-admin check → bot-permission check →
  perform action → confirmation reply.

The bot-permission check inspects can_pin_messages SPECIFICALLY on the
bot's own ChatMember.privileges — generic admin status does not imply
that right (same lesson as the invite-link rights in playback.py).
"""

import html
import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode

from bot.utils import emoji as e

logger = logging.getLogger("WarbornMusic.pin")

_HTML = ParseMode.HTML

_ADMIN_STATUSES = (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


async def _is_admin(client, chat_id, user_id) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in _ADMIN_STATUSES


async def _bot_can_pin(client, chat_id) -> bool:
    """True iff the bot's own chat-member privileges include can_pin_messages."""
    try:
        me = await client.get_me()
        member = await client.get_chat_member(chat_id, me.id)
    except Exception:
        return False
    if member.status == ChatMemberStatus.OWNER:
        return True
    privs = getattr(member, "privileges", None)
    return bool(privs and getattr(privs, "can_pin_messages", False))


async def _guard(client, message, *, action: str) -> bool:
    """Shared chat-type + caller-admin + bot-permission gate. Returns True
    if all checks pass (caller may proceed), False after replying otherwise.
    """
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            f"{e.PEOPLE} <b>Groups only</b>\n"
            f"<i>/{action} works inside a group.</i>", parse_mode=_HTML)
        return False
    if not message.from_user or not await _is_admin(client, message.chat.id, message.from_user.id):
        await message.reply_text(
            "🔒 <b>Admins only</b>\n"
            f"<i>Only group admins can /{action}.</i>", parse_mode=_HTML)
        return False
    if not await _bot_can_pin(client, message.chat.id):
        await message.reply_text(
            f"⚠️ {e.SHIELD} <b>I need permission</b>\n"
            "<i>Enable the <b>Pin Messages</b> admin right for me, then try again.</i>",
            parse_mode=_HTML)
        return False
    return True


@Client.on_message(filters.command("pin"))
async def pin_command(client, message):
    if not await _guard(client, message, action="pin"):
        return

    reply = message.reply_to_message
    if not reply:
        await message.reply_text(
            "📌 <b>Pin — how to use</b>\n"
            "<i>Reply to a message with</i> <code>/pin</code>\n"
            "• <code>/pin</code> — <i>silent pin</i>\n"
            "• <code>/pin loud</code> — <i>pin and notify members</i>",
            parse_mode=_HTML)
        return

    args = [a.lower() for a in message.command[1:]]
    loud = any(a in ("loud", "notify") for a in args)

    logger.info(
        "pin attempt: chat=%s reply_msg_id=%s reply_thread=%s loud=%s reply_repr=%r",
        message.chat.id, reply.id,
        getattr(reply, "message_thread_id", None),
        loud, reply,
    )
    try:
        result = await client.pin_chat_message(
            chat_id=message.chat.id,
            message_id=reply.id,
            disable_notification=not loud,
        )
        logger.info("pin_chat_message returned type=%s value=%r", type(result).__name__, result)
    except Exception as exc:
        logger.exception(
            "pin failed: type=%s id=%s message=%s",
            type(exc).__name__, getattr(exc, "ID", None), getattr(exc, "MESSAGE", None),
        )
        _id = f" [{exc.ID}]" if getattr(exc, "ID", None) else ""
        await message.reply_text(
            "❌ <b>Pin failed</b>\n"
            f"<code>{html.escape(type(exc).__name__ + _id + ': ' + str(getattr(exc, 'MESSAGE', None) or exc))}</code>",
            parse_mode=_HTML)
        return

    await message.reply_text(
        f"📌 <b>Pinned</b> · <i>by</i> {e.mention(message.from_user)}", parse_mode=_HTML)


@Client.on_message(filters.command("unpin"))
async def unpin_command(client, message):
    if not await _guard(client, message, action="unpin"):
        return

    reply = message.reply_to_message
    try:
        if reply:
            await client.unpin_chat_message(message.chat.id, reply.id)
            await message.reply_text(
                f"📌 <b>Unpinned</b> · <i>by</i> {e.mention(message.from_user)}",
                parse_mode=_HTML)
        else:
            # No reply → unpin the most recent pin.
            await client.unpin_chat_message(message.chat.id)
            await message.reply_text(
                f"📌 <b>Unpinned the latest pin</b>\n"
                f"<i>Reply to a specific message to target it — by</i> "
                f"{e.mention(message.from_user)}", parse_mode=_HTML)
    except Exception as exc:
        await message.reply_text(
            "❌ <b>Unpin failed</b>\n"
            f"<code>{html.escape(str(exc))}</code>", parse_mode=_HTML)


@Client.on_message(filters.command("unpinall"))
async def unpinall_command(client, message):
    if not await _guard(client, message, action="unpinall"):
        return

    # Destructive — require explicit confirmation.
    args = [a.lower() for a in message.command[1:]]
    if "confirm" not in args:
        await message.reply_text(
            "⚠️ <b>This clears ALL pinned messages</b>\n"
            "<i>Re-run as</i> <code>/unpinall confirm</code> <i>to proceed.</i>",
            parse_mode=_HTML)
        return

    try:
        await client.unpin_all_chat_messages(message.chat.id)
    except Exception as exc:
        await message.reply_text(
            "❌ <b>Unpin-all failed</b>\n"
            f"<code>{html.escape(str(exc))}</code>", parse_mode=_HTML)
        return

    await message.reply_text(
        f"📌 <b>Cleared all pins</b> · <i>by</i> {e.mention(message.from_user)}",
        parse_mode=_HTML)
