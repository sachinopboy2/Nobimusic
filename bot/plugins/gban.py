"""/gban, /removegban — global ban / unban across every chat the bot is in.

Sudo-only (owner counts as sudo). The same target resolution as /ban:
- reply to a message
- /gban <user_id>
- /gban @username
- text-mention entity (covers usernameless tagged users)

A passive ChatMemberUpdated handler also auto-bans gbanned users the
moment they enter any chat the bot sees. So even if a fan-out missed a
chat (because the bot wasn't admin yet), the ban gets applied when the
user later tries to come back.
"""

import asyncio
import html
import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType, MessageEntityType, ParseMode
from pyrogram.errors import FloodWait

from bot.utils import chats, emoji as e, gban
from bot.utils.owner import is_sudo

logger = logging.getLogger("WarbornMusic.gban")

_HTML = ParseMode.HTML

# Spread the per-chat bans so we don't trip Telegram's rate limits.
_FANOUT_DELAY = 0.05


async def _resolve_target(client, message):
    """Return (user_id, mention_html, reason) for the gban target."""
    text = message.text or ""

    # text-mention entity
    for ent in (message.entities or []):
        if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
            mention_text = text[ent.offset:ent.offset + ent.length]
            after_cmd = text.split(maxsplit=1)
            after_cmd = after_cmd[1] if len(after_cmd) > 1 else ""
            reason = after_cmd.replace(mention_text, "", 1).strip()
            return ent.user.id, e.mention(ent.user), reason

    # reply
    reply = message.reply_to_message
    if reply and reply.from_user:
        reason = " ".join(message.command[1:]).strip()
        return reply.from_user.id, e.mention(reply.from_user), reason

    if len(message.command) < 2:
        return None, None, ""

    raw = message.command[1].lstrip("@")
    reason = " ".join(message.command[2:]).strip()

    from bot.client import userbot
    try:
        if raw.isdigit():
            user = await client.get_users(int(raw))
        else:
            try:
                user = await userbot.get_users(raw)
            except Exception:
                user = await client.get_users(raw)
        return user.id, e.mention(user), reason
    except Exception:
        if raw.isdigit():
            return int(raw), f'<a href="tg://user?id={raw}">user {raw}</a>', reason
        return None, None, reason


async def _fanout(client, action: str, user_id: int) -> tuple[int, int, int]:
    """Apply ban or unban across every registered chat.

    action: "ban" or "unban".
    Returns (success_count, skipped_no_admin_count, error_count).
    """
    success = 0
    skipped = 0
    errored = 0
    for chat_id in chats.all_chats():
        if chat_id > 0:
            # DMs — there's nothing to ban there.
            continue
        try:
            if action == "ban":
                await client.ban_chat_member(chat_id, user_id)
            else:
                await client.unban_chat_member(chat_id, user_id)
            success += 1
        except FloodWait as fw:
            wait = int(getattr(fw, "value", None) or getattr(fw, "x", 30))
            await asyncio.sleep(wait + 1)
            try:
                if action == "ban":
                    await client.ban_chat_member(chat_id, user_id)
                else:
                    await client.unban_chat_member(chat_id, user_id)
                success += 1
            except Exception as exc2:
                errored += 1
                logger.info("%s in %s retry failed: %s", action, chat_id, exc2)
        except Exception as exc:
            name = type(exc).__name__
            text = str(exc).lower()
            if "not enough rights" in text or "admin" in text or name in (
                "ChatAdminRequired", "RightForbidden",
            ):
                skipped += 1
            else:
                errored += 1
                logger.info("%s in %s failed: %s: %s", action, chat_id, name, exc)
        await asyncio.sleep(_FANOUT_DELAY)
    return success, skipped, errored


@Client.on_message(filters.command("gban"))
async def gban_command(client, message):
    if not message.from_user or not await is_sudo(message.from_user.id):
        await message.reply_text(
            f"🔒 {e.SHIELD} <b>Sudo only</b>\n"
            "<i>/gban is for sudo users.</i>", parse_mode=_HTML)
        return

    target_id, mention, reason = await _resolve_target(client, message)
    if target_id is None:
        await message.reply_text(
            f"{e.SHIELD} <b>Global ban — how to use</b>\n"
            "• <i>Reply to a user with</i> <code>/gban [reason]</code>\n"
            "• <code>/gban &lt;user_id&gt; [reason]</code>\n"
            "• <code>/gban @username [reason]</code>", parse_mode=_HTML)
        return

    me = await client.get_me()
    if target_id == me.id:
        await message.reply_text("🙃 <b>I'm not going to gban myself.</b>", parse_mode=_HTML)
        return
    if await is_sudo(target_id):
        await message.reply_text("🔒 <b>I won't gban another sudoer.</b>", parse_mode=_HTML)
        return

    is_new = gban.add(target_id, reason=reason, by_user=message.from_user.id)
    status = await message.reply_text(
        f"🔨 <b>Global-banning</b> {mention}{'…' if is_new else ' (updating reason)…'}",
        parse_mode=_HTML,
    )
    success, skipped, errored = await _fanout(client, "ban", target_id)

    summary = (
        f"{e.SHIELD} <b>Globally banned</b> 🚫\n"
        f"<b>User:</b> {mention}\n"
        + (f"<b>Reason:</b> {html.escape(reason)}\n" if reason else "")
        + f"\n"
        f"✅ <b>Banned in:</b> {success} chat(s)\n"
        f"⚠️ <b>Skipped (no admin):</b> {skipped}\n"
        f"❌ <b>Errors:</b> {errored}\n"
        f"📊 <b>Gban list size:</b> {gban.count()}"
    )
    await status.edit_text(summary, parse_mode=_HTML)


@Client.on_message(filters.command(["removegban", "ungban", "delgban"]))
async def removegban_command(client, message):
    if not message.from_user or not await is_sudo(message.from_user.id):
        await message.reply_text(
            f"🔒 {e.SHIELD} <b>Sudo only</b>\n"
            "<i>/removegban is for sudo users.</i>", parse_mode=_HTML)
        return

    target_id, mention, _ = await _resolve_target(client, message)
    if target_id is None:
        await message.reply_text(
            f"{e.SHIELD} <b>Remove global ban — how to use</b>\n"
            "• <i>Reply to a user with</i> <code>/removegban</code>\n"
            "• <code>/removegban &lt;user_id&gt;</code>\n"
            "• <code>/removegban @username</code>", parse_mode=_HTML)
        return

    was_banned = gban.remove(target_id)
    if not was_banned:
        await message.reply_text(
            f"ℹ️ {mention} <b>wasn't on the gban list</b> — nothing to undo.",
            parse_mode=_HTML,
        )
        return

    status = await message.reply_text(
        f"🔓 <b>Removing global ban for</b> {mention}…", parse_mode=_HTML
    )
    success, skipped, errored = await _fanout(client, "unban", target_id)

    summary = (
        f"✅ <b>Global ban removed</b>\n"
        f"<b>User:</b> {mention}\n\n"
        f"✅ <b>Unbanned in:</b> {success} chat(s)\n"
        f"⚠️ <b>Skipped (no admin):</b> {skipped}\n"
        f"❌ <b>Errors:</b> {errored}\n"
        f"📊 <b>Gban list size:</b> {gban.count()}"
    )
    await status.edit_text(summary, parse_mode=_HTML)


# Passive enforcement: when a gbanned user appears in any chat the bot
# can see, ban them on the spot. Catches the "missed a chat during
# fanout" case and the "user re-joined after we banned" case.
@Client.on_chat_member_updated()
async def _enforce_gban_on_join(client, update):
    new = getattr(update, "new_chat_member", None)
    if new is None or new.user is None:
        return
    user = new.user
    if user.is_bot or getattr(user, "is_self", False):
        return
    if not gban.is_banned(user.id):
        return
    # Only act if they're currently present in the chat.
    if new.status not in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED):
        return
    try:
        await client.ban_chat_member(update.chat.id, user.id)
        logger.info(
            "enforced gban: banned %s in %s on join", user.id, update.chat.id
        )
    except Exception as exc:
        logger.info(
            "enforce gban failed for %s in %s: %s: %s",
            user.id, update.chat.id, type(exc).__name__, exc,
        )
