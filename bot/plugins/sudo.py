"""/addsudo, /delsudo, /sudolist — owner-managed delegation of privileges.

The bot's OWNER (env OWNER_ID, defaults to the userbot.id) is implicit
sudo and can never be removed. Sudoers granted here can run commands
gated by `is_sudo` (currently /broadcast, /seeddm).

Resolution rules for target user (same shape as /ban):
- text_mention entity in the command message
- reply to a user's message
- /addsudo <user_id>
- /addsudo @username (resolved via the userbot since the bot API can't
  always resolve arbitrary @usernames)
"""

from pyrogram import Client, filters
from pyrogram.enums import MessageEntityType, ParseMode

from bot.utils import emoji as e
from bot.utils import sudo as sudo_store
from bot.utils.owner import get_owner_ids, is_owner, is_sudo

_HTML = ParseMode.HTML


async def _owner_denied_text(user_id: int) -> str:
    owners = await get_owner_ids()
    if not owners:
        return (
            "🔒 This command is owner-only — but no owner is configured.\n\n"
            f"Set <code>OWNER_ID={user_id}</code> in the bot's .env "
            "(comma-separated for multiple owners) and restart."
        )
    return (
        "🔒 This command is owner-only.\n\n"
        f"Your ID: <code>{user_id}</code>\n"
        f"Configured owner(s): <code>{', '.join(str(i) for i in sorted(owners))}</code>\n\n"
        "If that should be you, set OWNER_ID in the bot's .env and restart."
    )


async def _sudo_denied_text(user_id: int) -> str:
    owners = await get_owner_ids()
    return (
        "🔒 This command is sudo-only.\n\n"
        f"Your ID: <code>{user_id}</code>\n"
        f"Configured owner(s): <code>{', '.join(str(i) for i in sorted(owners)) or '(none)'}</code>\n\n"
        "Owner can grant access with /addsudo, or set OWNER_ID/SUDO_USERS in .env."
    )


async def _resolve_user(client, message):
    """Return (user_id, mention_html) for the addsudo/delsudo target."""
    text = message.text or ""

    # text-mention entity (covers usernameless tagged users)
    for ent in (message.entities or []):
        if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
            return ent.user.id, e.mention(ent.user)

    # reply
    reply = message.reply_to_message
    if reply and reply.from_user:
        return reply.from_user.id, e.mention(reply.from_user)

    if len(message.command) < 2:
        return None, None

    raw = message.command[1].lstrip("@")

    from bot.client import userbot
    try:
        if raw.isdigit():
            u = await client.get_users(int(raw))
        else:
            try:
                u = await userbot.get_users(raw)
            except Exception:
                u = await client.get_users(raw)
        return u.id, e.mention(u)
    except Exception:
        # Last-resort: trust the id we were given even if we can't fetch
        # a User object for the pretty-print.
        if raw.isdigit():
            return int(raw), f'<a href="tg://user?id={raw}">user {raw}</a>'
        return None, None


@Client.on_message(filters.command("addsudo"))
async def addsudo_command(client, message):
    if not message.from_user:
        return
    if not await is_owner(message.from_user.id):
        await message.reply_text(
            await _owner_denied_text(message.from_user.id), parse_mode=ParseMode.HTML
        )
        return

    target_id, mention = await _resolve_user(client, message)
    if target_id is None:
        await message.reply_text(
            f"{e.CROWN} <b>Add sudo — how to use</b>\n"
            "• <i>Reply to a user with</i> <code>/addsudo</code>\n"
            "• <code>/addsudo &lt;user_id&gt;</code>\n"
            "• <code>/addsudo @username</code>", parse_mode=_HTML)
        return

    if await is_owner(target_id):
        await message.reply_text(
            "ℹ️ <b>The owner is already implicit sudo.</b>", parse_mode=_HTML)
        return

    if sudo_store.add(target_id):
        await message.reply_text(
            f"✅ {e.CROWN} <b>Added to sudo</b>\n{mention}", parse_mode=_HTML)
    else:
        await message.reply_text(
            f"ℹ️ {mention} <b>was already a sudoer.</b>", parse_mode=_HTML)


@Client.on_message(filters.command(["delsudo", "removesudo", "rmsudo"]))
async def delsudo_command(client, message):
    if not message.from_user:
        return
    if not await is_owner(message.from_user.id):
        await message.reply_text(
            await _owner_denied_text(message.from_user.id), parse_mode=ParseMode.HTML
        )
        return

    target_id, mention = await _resolve_user(client, message)
    if target_id is None:
        await message.reply_text(
            f"{e.CROWN} <b>Remove sudo — how to use</b>\n"
            "• <i>Reply to a user with</i> <code>/delsudo</code>\n"
            "• <code>/delsudo &lt;user_id&gt;</code>\n"
            "• <code>/delsudo @username</code>", parse_mode=_HTML)
        return

    if sudo_store.remove(target_id):
        await message.reply_text(
            f"✅ <b>Removed from sudo</b>\n{mention}", parse_mode=_HTML)
    else:
        await message.reply_text(
            f"ℹ️ {mention} <b>wasn't a sudoer.</b>", parse_mode=_HTML)


@Client.on_message(filters.command(["sudolist", "sudoers"]))
async def sudolist_command(client, message):
    if not message.from_user:
        return
    if not await is_sudo(message.from_user.id):
        await message.reply_text(
            await _sudo_denied_text(message.from_user.id), parse_mode=ParseMode.HTML
        )
        return

    sudoers = sudo_store.all_sudoers()
    if not sudoers:
        await message.reply_text(
            f"{e.CROWN} <b>No additional sudoers yet</b>\n"
            "<i>The owner is implicit sudo.</i>", parse_mode=_HTML)
        return

    lines = [f"{e.CROWN} <b>Sudoers</b>"]
    for uid in sudoers:
        try:
            u = await client.get_users(uid)
            lines.append(f"• {e.mention(u)} (<code>{uid}</code>)")
        except Exception:
            lines.append(f"• <code>{uid}</code>")
    await message.reply_text("\n".join(lines), parse_mode=_HTML)
