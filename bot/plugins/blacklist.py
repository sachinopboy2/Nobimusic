import html
import logging

from pyrogram import Client, filters
from pyrogram.enums import MessageEntityType, ParseMode

from bot.client import userbot
from bot.utils import blacklist as bl
from bot.utils import emoji as e
from bot.utils.owner import get_owner_ids, is_sudo

logger = logging.getLogger("WarbornMusic.blacklist")

_HTML = ParseMode.HTML


async def _resolve_target(client, message):
    for ent in (message.entities or []):
        if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
            text_mention = (message.text or "")[ent.offset:ent.offset + ent.length]
            reason = " ".join(message.command[1:]).replace(text_mention, "", 1).strip()
            return ent.user, reason, None

    reply = message.reply_to_message
    if reply and reply.from_user:
        return reply.from_user, " ".join(message.command[1:]).strip(), None

    if len(message.command) < 2:
        return None, "", None

    raw = message.command[1].lstrip("@")
    reason = " ".join(message.command[2:]).strip()
    try:
        if raw.lstrip("-").isdigit():
            return await client.get_users(int(raw)), reason, None
        try:
            return await userbot.get_users(raw), reason, None
        except Exception:
            return await client.get_users(raw), reason, None
    except Exception as exc:
        return None, "", f"Couldn't resolve {raw}: {exc}"


# group=-3 runs before broadcast tracker (group=-1) and every command
# handler (group=0). Catches messages from blacklisted users and stops
# propagation so the bot ignores them entirely — no command response,
# no linksniffer auto-download, no chat-registry track.
@Client.on_message(filters.all, group=-3)
async def _intercept_blacklisted(client, message):
    user = message.from_user
    if user is None or not bl.is_blacklisted(user.id):
        return
    # Don't block owner/sudo even if accidentally added.
    if await is_sudo(user.id):
        return
    logger.info("blacklist: dropped message from user=%s chat=%s",
                user.id, message.chat.id if message.chat else None)
    message.stop_propagation()


@Client.on_message(filters.command("blist"))
async def blist_command(client, message):
    if not message.from_user or not await is_sudo(message.from_user.id):
        owners = await get_owner_ids()
        await message.reply_text(
            f"🔒 {e.SHIELD} <b>Sudo only</b>\n"
            f"<b>Your ID:</b> <code>{message.from_user.id}</code>\n"
            f"<b>Owners:</b> <code>{', '.join(str(i) for i in sorted(owners)) or '(none)'}</code>",
            parse_mode=_HTML)
        return

    target, reason, err = await _resolve_target(client, message)
    if target is None:
        if err:
            await message.reply_text(f"❌ {html.escape(err)}", parse_mode=_HTML)
        else:
            await message.reply_text(
                f"{e.SHIELD} <b>Blacklist — how to use</b>\n"
                "• <i>Reply with</i> <code>/blist [reason]</code>\n"
                "• <code>/blist &lt;user_id&gt; [reason]</code>\n"
                "• <code>/blist @username [reason]</code>", parse_mode=_HTML)
        return

    me = await client.get_me()
    if target.id == me.id:
        await message.reply_text("🙃 <b>Can't blacklist myself.</b>", parse_mode=_HTML)
        return
    if await is_sudo(target.id):
        await message.reply_text("🔒 <b>Can't blacklist a sudo user.</b>", parse_mode=_HTML)
        return

    was_new = bl.add(target.id, reason=reason, by_user=message.from_user.id)
    verb = "Blacklisted" if was_new else "Blacklist updated"
    tail = f"\n<b>Reason:</b> {html.escape(reason)}" if reason else ""
    await message.reply_text(
        f"⛔ {e.SHIELD} <b>{verb}</b>\n"
        f"<b>User:</b> {e.mention(target)}\n"
        f"<b>By:</b> {e.mention(message.from_user)}{tail}\n"
        f"<b>Total blacklisted:</b> {bl.count()}", parse_mode=_HTML)


@Client.on_message(filters.command(["unblist", "removeblist"]))
async def unblist_command(client, message):
    if not message.from_user or not await is_sudo(message.from_user.id):
        await message.reply_text(
            f"🔒 {e.SHIELD} <b>Sudo only</b>\n"
            "<i>/unblist is for sudo users.</i>", parse_mode=_HTML)
        return

    target, _reason, err = await _resolve_target(client, message)
    if target is None:
        if err:
            await message.reply_text(f"❌ {html.escape(err)}", parse_mode=_HTML)
        else:
            await message.reply_text(
                f"{e.SHIELD} <b>Un-blacklist — how to use</b>\n"
                "• <i>Reply with</i> <code>/unblist</code>\n"
                "• <code>/unblist &lt;user_id&gt;</code>\n"
                "• <code>/unblist @username</code>", parse_mode=_HTML)
        return

    removed = bl.remove(target.id)
    if not removed:
        await message.reply_text(
            f"➖ {e.mention(target)} <b>wasn't blacklisted.</b>", parse_mode=_HTML)
        return
    await message.reply_text(
        f"✅ <b>Removed from blacklist</b>\n"
        f"<b>User:</b> {e.mention(target)}\n"
        f"<b>By:</b> {e.mention(message.from_user)}\n"
        f"<b>Total blacklisted:</b> {bl.count()}", parse_mode=_HTML)
