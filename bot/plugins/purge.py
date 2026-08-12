"""/purge — bulk message deletion for group admins.

Three modes (auto-detected from args):
  • Reply, no args     → delete replied msg .. command msg (inclusive)
  • /purge <n>         → delete the last n messages + the command
  • /purge <n> min     → delete everything from the last n minutes

Structural pattern mirrors bot/plugins/ban.py. Bot-permission check
inspects can_delete_messages SPECIFICALLY on the bot's own privileges.

IMPORTANT tz note: pyrofork's message.date is a NAIVE datetime
(datetime.fromtimestamp(ts), local time) in this version — confirmed
against pyrogram/utils.timestamp_to_datetime. So the time-window cutoff
is computed with a naive datetime.now(); using datetime.now(timezone.utc)
would raise on the naive/aware comparison.
"""

from datetime import datetime, timedelta

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode

from bot.utils import emoji as e

_HTML = ParseMode.HTML

_ADMIN_STATUSES = (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)

# Telegram per-call delete cap and our own safety cap.
_DELETE_BATCH = 100
_MAX_PER_CALL = 200

_MIN_WORDS = ("min", "mins", "minute", "minutes", "m")


async def _is_admin(client, chat_id, user_id) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in _ADMIN_STATUSES


async def _bot_can_delete(client, chat_id) -> bool:
    try:
        me = await client.get_me()
        member = await client.get_chat_member(chat_id, me.id)
    except Exception:
        return False
    if member.status == ChatMemberStatus.OWNER:
        return True
    privs = getattr(member, "privileges", None)
    return bool(privs and getattr(privs, "can_delete_messages", False))


async def _delete_ids(client, chat_id, ids: list[int]) -> None:
    """Delete message ids in batches of 100 (Telegram per-call cap)."""
    for i in range(0, len(ids), _DELETE_BATCH):
        batch = ids[i:i + _DELETE_BATCH]
        try:
            await client.delete_messages(chat_id, batch)
        except Exception:
            # Bots can't delete >48h-old messages; those silently no-op or
            # raise per-batch. Swallow so one bad batch doesn't abort the rest.
            pass


@Client.on_message(filters.command("purge"))
async def purge_command(client, message):
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            f"{e.PEOPLE} <b>Groups only</b>\n"
            "<i>/purge works inside a group.</i>", parse_mode=_HTML)
        return
    if not message.from_user or not await _is_admin(client, message.chat.id, message.from_user.id):
        await message.reply_text(
            "🔒 <b>Admins only</b>\n"
            "<i>Only group admins can /purge.</i>", parse_mode=_HTML)
        return
    if not await _bot_can_delete(client, message.chat.id):
        await message.reply_text(
            f"⚠️ {e.SHIELD} <b>I need permission</b>\n"
            "<i>Enable the <b>Delete Messages</b> admin right for me, then try again.</i>",
            parse_mode=_HTML)
        return

    chat_id = message.chat.id
    args = message.command[1:]
    reply = message.reply_to_message

    # ── Mode 1: reply-based range ──
    if reply and not args:
        start_id, end_id = reply.id, message.id
        ids = list(range(start_id, end_id + 1))
        if len(ids) > _MAX_PER_CALL:
            await message.reply_text(
                f"⚠️ <b>Range too large</b>\n"
                f"<i>{len(ids)} messages — over the {_MAX_PER_CALL} per-call cap. "
                "Purge in smaller chunks.</i>", parse_mode=_HTML)
            return
        await _delete_ids(client, chat_id, ids)
        # Exclude the command message itself from the displayed count.
        await client.send_message(
            chat_id, f"🧹 <b>Purged {len(ids) - 1} messages.</b>", parse_mode=_HTML)
        return

    # ── Mode 3: time-window ──  /purge <n> min
    if len(args) >= 2 and args[0].lstrip("-").isdigit() and args[1].lower() in _MIN_WORDS:
        minutes = int(args[0])
        if minutes <= 0:
            await message.reply_text(
                "⚠️ <b>Minutes must be a positive number.</b>", parse_mode=_HTML)
            return
        cutoff = datetime.now() - timedelta(minutes=minutes)
        ids: list[int] = []
        hit_cap = False
        async for msg in client.get_chat_history(chat_id):
            if msg.date is None:
                continue
            if msg.date < cutoff:
                # History is newest-first — everything past here is older too.
                break
            ids.append(msg.id)
            if len(ids) >= _MAX_PER_CALL:
                hit_cap = True
                break
        await _delete_ids(client, chat_id, ids)
        shown = max(len(ids) - 1, 0)  # command msg falls in-window; don't count it
        if hit_cap:
            await client.send_message(
                chat_id,
                f"🧹 <b>Purged {shown} messages</b>\n"
                f"<i>Hit the per-call cap — more may remain in the last {minutes} min, "
                "run /purge again.</i>", parse_mode=_HTML)
        else:
            await client.send_message(
                chat_id, f"🧹 <b>Purged {shown} messages.</b>", parse_mode=_HTML)
        return

    # ── Mode 2: count-based ──  /purge <n>
    if len(args) == 1 and args[0].lstrip("-").isdigit():
        n = int(args[0])
        if n <= 0:
            await message.reply_text(
                "⚠️ <b>Count must be a positive number.</b>", parse_mode=_HTML)
            return
        n = min(n, _MAX_PER_CALL)
        ids = [message.id]  # the command itself
        async for msg in client.get_chat_history(chat_id, limit=n):
            if msg.id != message.id:
                ids.append(msg.id)
        await _delete_ids(client, chat_id, ids)
        await client.send_message(
            chat_id, f"🧹 <b>Purged {len(ids) - 1} messages.</b>", parse_mode=_HTML)
        return

    # ── No recognised form → usage ──
    await message.reply_text(
        "🧹 <b>Purge — how to use</b>\n"
        "• <i>Reply to a message with</i> <code>/purge</code> — <i>delete from there to now</i>\n"
        "• <code>/purge &lt;n&gt;</code> — <i>delete the last n messages</i>\n"
        "• <code>/purge &lt;n&gt; min</code> — <i>delete the last n minutes</i>\n\n"
        f"<i>Max {_MAX_PER_CALL} per call. Messages older than 48h can't be "
        "deleted and are skipped.</i>", parse_mode=_HTML)
