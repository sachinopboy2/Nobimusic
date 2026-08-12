import html
import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType, MessageEntityType, ParseMode
from pyrogram.types import ChatAdministratorRights

from bot.client import userbot
from bot.utils import emoji as e

logger = logging.getLogger("WarbornMusic.promote")

_HTML = ParseMode.HTML

_ADMIN_STATUSES = (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


async def _is_admin(client, chat_id, user_id) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in _ADMIN_STATUSES


async def _resolve_target(client, message):
    """Return (user, title, error).

    title rules:
      • reply + /<cmd> tail → tail is the title
      • /<cmd> <user> <tail…> → tail is the title
      • title is None if nothing followed
    Telegram caps admin titles at 16 chars; longer strings get truncated.
    """
    for ent in (message.entities or []):
        if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
            title = " ".join(message.command[1:]).strip() or None
            text_mention = (message.text or "")[ent.offset:ent.offset + ent.length]
            if title:
                title = title.replace(text_mention, "", 1).strip() or None
            return ent.user, (title[:16] if title else None), None

    reply = message.reply_to_message
    if reply and reply.from_user:
        title = " ".join(message.command[1:]).strip() or None
        return reply.from_user, (title[:16] if title else None), None

    if len(message.command) < 2:
        return None, None, None

    raw = message.command[1].lstrip("@")
    title = " ".join(message.command[2:]).strip() or None
    title = title[:16] if title else None
    try:
        if raw.lstrip("-").isdigit():
            return await client.get_users(int(raw)), title, None
        try:
            return await userbot.get_users(raw), title, None
        except Exception:
            return await client.get_users(raw), title, None
    except Exception as exc:
        return None, None, f"Couldn't resolve {raw}: {exc}"


@Client.on_message(filters.command(["promote", "feature"]))
async def promote_command(client, message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            f"{e.PEOPLE} <b>Groups only</b>\n"
            "<i>/promote works inside a group.</i>", parse_mode=_HTML)
        return
    if not message.from_user or not await _is_admin(client, message.chat.id, message.from_user.id):
        await message.reply_text(
            "🔒 <b>Admins only</b>\n"
            "<i>Only group admins can /promote.</i>", parse_mode=_HTML)
        return

    me = await client.get_me()
    try:
        me_member = await client.get_chat_member(message.chat.id, me.id)
    except Exception:
        me_member = None
    if me_member is None or me_member.status != ChatMemberStatus.ADMINISTRATOR:
        await message.reply_text(
            f"⚠️ {e.CROWN} <b>I need permission</b>\n"
            "<i>Make me an admin with <b>Add New Admins</b> rights.</i>", parse_mode=_HTML)
        return
    privs = getattr(me_member, "privileges", None)
    if not privs or not getattr(privs, "can_promote_members", False):
        await message.reply_text(
            f"⚠️ {e.CROWN} <b>Missing right</b>\n"
            "<i>I don't have the <b>Add New Admins</b> admin right.</i>", parse_mode=_HTML)
        return

    target, title, err = await _resolve_target(client, message)
    if target is None:
        if err:
            await message.reply_text(f"❌ {html.escape(err)}", parse_mode=_HTML)
        else:
            await message.reply_text(
                f"{e.CROWN} <b>Promote — how to use</b>\n"
                "• <i>Reply with</i> <code>/promote [title]</code>\n"
                "• <code>/promote &lt;user_id&gt; [title]</code>\n"
                "• <code>/promote @username [title]</code>", parse_mode=_HTML)
        return

    if target.id == me.id:
        await message.reply_text("🙃 <b>Can't promote myself.</b>", parse_mode=_HTML)
        return

    rights = ChatAdministratorRights(
        is_anonymous=False,
        can_manage_chat=True,
        can_delete_messages=True,
        can_manage_video_chats=True,
        can_restrict_members=True,
        can_promote_members=False,
        can_change_info=True,
        can_invite_users=True,
        can_pin_messages=True,
    )

    try:
        await client.promote_chat_member(message.chat.id, target.id, privileges=rights)
    except Exception as exc:
        logger.exception("promote failed: id=%s message=%s", getattr(exc, "ID", None), getattr(exc, "MESSAGE", None))
        _id = f" [{exc.ID}]" if getattr(exc, "ID", None) else ""
        await message.reply_text(
            "❌ <b>Promote failed</b>\n"
            f"<code>{html.escape(type(exc).__name__ + _id + ': ' + str(getattr(exc, 'MESSAGE', None) or exc))}</code>",
            parse_mode=_HTML)
        return

    title_note = ""
    if title:
        try:
            await client.set_administrator_title(message.chat.id, target.id, title)
            title_note = f"\n🏷 <b>Title:</b> {html.escape(title)}"
        except Exception as exc:
            # Promotion succeeded; just the title set failed.
            logger.exception("set_administrator_title failed")
            title_note = (
                f"\n⚠️ <i>Title not set: "
                f"{html.escape(str(getattr(exc, 'MESSAGE', None) or exc))}</i>"
            )

    await message.reply_text(
        f"{e.CROWN} <b>Promoted to admin</b> ⭐\n"
        f"<b>User:</b> {e.mention(target)}\n"
        f"<b>By:</b> {e.mention(message.from_user)}{title_note}",
        parse_mode=_HTML)


@Client.on_message(filters.command(["demote", "unpromote"]))
async def demote_command(client, message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            f"{e.PEOPLE} <b>Groups only</b>\n"
            "<i>/demote works inside a group.</i>", parse_mode=_HTML)
        return
    if not message.from_user or not await _is_admin(client, message.chat.id, message.from_user.id):
        await message.reply_text(
            "🔒 <b>Admins only</b>\n"
            "<i>Only group admins can /demote.</i>", parse_mode=_HTML)
        return

    me = await client.get_me()
    try:
        me_member = await client.get_chat_member(message.chat.id, me.id)
    except Exception:
        me_member = None
    if me_member is None or me_member.status != ChatMemberStatus.ADMINISTRATOR:
        await message.reply_text(
            f"⚠️ {e.CROWN} <b>I need permission</b>\n"
            "<i>Make me an admin with <b>Add New Admins</b> rights.</i>", parse_mode=_HTML)
        return
    privs = getattr(me_member, "privileges", None)
    if not privs or not getattr(privs, "can_promote_members", False):
        await message.reply_text(
            f"⚠️ {e.CROWN} <b>Missing right</b>\n"
            "<i>I don't have the <b>Add New Admins</b> admin right.</i>", parse_mode=_HTML)
        return

    target, _title, err = await _resolve_target(client, message)
    if target is None:
        if err:
            await message.reply_text(f"❌ {html.escape(err)}", parse_mode=_HTML)
        else:
            await message.reply_text(
                f"{e.CROWN} <b>Demote — how to use</b>\n"
                "• <i>Reply with</i> <code>/demote</code>\n"
                "• <code>/demote &lt;user_id&gt;</code>\n"
                "• <code>/demote @username</code>", parse_mode=_HTML)
        return

    if target.id == me.id:
        await message.reply_text("🙃 <b>Can't demote myself.</b>", parse_mode=_HTML)
        return

    # All-False privilege set demotes an admin back to plain member.
    zero = ChatAdministratorRights(
        is_anonymous=False,
        can_manage_chat=False,
        can_delete_messages=False,
        can_manage_video_chats=False,
        can_restrict_members=False,
        can_promote_members=False,
        can_change_info=False,
        can_invite_users=False,
        can_pin_messages=False,
    )

    try:
        await client.promote_chat_member(message.chat.id, target.id, privileges=zero)
    except Exception as exc:
        logger.exception("demote failed: id=%s message=%s", getattr(exc, "ID", None), getattr(exc, "MESSAGE", None))
        _id = f" [{exc.ID}]" if getattr(exc, "ID", None) else ""
        await message.reply_text(
            "❌ <b>Demote failed</b>\n"
            f"<code>{html.escape(type(exc).__name__ + _id + ': ' + str(getattr(exc, 'MESSAGE', None) or exc))}</code>",
            parse_mode=_HTML)
        return

    await message.reply_text(
        f"{e.CROWN} <b>Demoted</b> 💤\n"
        f"<b>User:</b> {e.mention(target)}\n"
        f"<b>By:</b> {e.mention(message.from_user)}", parse_mode=_HTML)
