"""/all — admin mass-mention of every group member, /cancel_all to stop it.

Mentions are batched (5 per message). Any text after /all becomes a
"📢 <text>" header above the mentions, preserving the argument's Telegram
entities (custom/premium emoji, bold, links, spoilers, …) by carrying its
HTML through the HTML sender; with no text, batches are bare mentions. When
/all is sent as a reply, EVERY batch replies to the original
message (any media type) so members see it alongside the mention. The send
loop runs as a background task so the handler returns immediately and
/cancel_all can interrupt it between batches. One operation per group.
"""

import asyncio
import html
import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode
from pyrogram.errors import FloodWait

from bot.utils import emoji as e

logger = logging.getLogger("WarbornMusic.all_tag")

_HTML = ParseMode.HTML
_ADMIN_STATUSES = (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
_GROUPS = (ChatType.GROUP, ChatType.SUPERGROUP)

_MENTIONS_PER_BATCH = 5
_PER_LINE = 5
_BATCH_PACING = 2.0  # seconds between batches (rate-limit friendly)
_DIVIDER = "━━━━━━━━━━━━━━"

# chat_id -> {"cancelled": bool, "task": Task}. Presence = an op is running.
_active: dict[int, dict] = {}


async def _is_admin(client, chat_id, user_id) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
    except Exception:
        return False
    return member.status in _ADMIN_STATUSES


async def _allowed(client, message) -> bool:
    # Group admins only. Anonymous admins post as the group itself.
    if message.from_user is None:
        sc = message.sender_chat
        return bool(sc and sc.id == message.chat.id)
    return await _is_admin(client, message.chat.id, message.from_user.id)


def _mention(user) -> str | None:
    if getattr(user, "is_bot", False) or getattr(user, "is_deleted", False):
        return None
    if getattr(user, "username", None):
        return f"@{user.username}"
    name = user.first_name or user.last_name
    if not name:
        return None
    return f'<a href="tg://user?id={user.id}">{html.escape(name)}</a>'


def _extract_custom(message) -> str:
    """The argument after the command, in HTML so its entities are preserved
    (custom/premium emoji, bold, italic, underline, strikethrough, spoilers,
    blockquotes, inline URLs, mentions, hashtags, …). Using the entity-aware
    HTML — not plain text — is what keeps CUSTOM_EMOJI ids attached; the
    HTML sender re-parses it and recomputes offsets. '' when no argument."""
    txt = getattr(message, "text", None)
    if not txt:
        return ""
    parts = txt.html.split(None, 1)  # split off "/all" (or "/all@bot")
    return parts[1].strip() if len(parts) > 1 else ""


def _render(custom, mentions) -> str:
    body = " ".join(mentions)  # <=5 mentions, single line
    if custom:
        return f"{e.MEGA} <b>{custom}</b>\n\n{body}"
    return body


def _reply_body(sender, custom, mentions) -> str:
    """Premium broadcast card used only in reply mode. Same mention formatting
    (" ".join) and same custom-text HTML as elsewhere — only the surrounding
    presentation changes: a broadcast banner, the admin, an optional note, and
    subtle separators around the mentions."""
    lines = [f"{e.MEGA} <b>Broadcast</b>  ✨", _DIVIDER]
    if sender:
        lines.append(f"{e.CROWN} <b>From</b> · {sender}")
    if custom:
        lines.append(f"{e.CHAT} {custom}")
    lines.append(_DIVIDER)
    lines.append(" ".join(mentions))
    return "\n".join(lines)


async def _send_batch(client, chat_id, body, reply_to):
    """Send one batch; retry FloodWait, fall back to a non-reply send if the
    reply target vanished. Returns the sent Message or None (unrecoverable)."""
    for reply in (reply_to, None):
        for _ in range(3):
            try:
                return await client.send_message(
                    chat_id, body, parse_mode=_HTML,
                    reply_to_message_id=reply, disable_web_page_preview=True,
                )
            except FloodWait as fw:
                await asyncio.sleep(int(getattr(fw, "value", 5)) + 1)
            except Exception as exc:
                logger.info("mass-tag send failed (reply=%s): %s", reply, exc)
                break  # try without reply_to
    return None


async def _run(client, chat_id, reply_first, custom, state, sender=""):
    try:
        members, seen = [], set()
        async for m in client.get_chat_members(chat_id):
            if state["cancelled"]:
                return
            user = getattr(m, "user", None)
            if user is None or user.id in seen:
                continue
            mention = _mention(user)
            if mention is None:
                continue
            seen.add(user.id)
            members.append(mention)

        if not members:
            await client.send_message(chat_id, "No members available to mention.", parse_mode=_HTML)
            return

        batches = (len(members) + _MENTIONS_PER_BATCH - 1) // _MENTIONS_PER_BATCH
        for bi in range(batches):
            if state["cancelled"]:
                return
            chunk = members[bi * _MENTIONS_PER_BATCH:(bi + 1) * _MENTIONS_PER_BATCH]
            if reply_first is not None:
                # Reply mode: premium broadcast card (still replies to original).
                body = _reply_body(sender, custom, chunk)
            elif not custom:
                # Plain /all (no text, no reply): premium call-out header.
                body = f"{e.PEOPLE} <b>Attention, everyone!</b>\n{_DIVIDER}\n{' '.join(chunk)}"
            else:
                # /all <text> (no reply): "📢 <text>" header. Unchanged.
                body = _render(custom, chunk)
            sent = await _send_batch(client, chat_id, body, reply_first)
            if sent is None:
                logger.warning("mass-tag aborted for chat=%s (send failed)", chat_id)
                return
            if bi + 1 < batches:
                await asyncio.sleep(_BATCH_PACING)
    finally:
        _active.pop(chat_id, None)


@Client.on_message(filters.command("all"))
async def all_cmd(client, message):
    if message.chat.type not in _GROUPS:
        await message.reply_text("👥 <b>Groups only</b>", parse_mode=_HTML)
        return
    if not await _allowed(client, message):
        await message.reply_text("🔒 <b>Admins only</b>\n<i>Only group admins can use /all.</i>", parse_mode=_HTML)
        return

    chat_id = message.chat.id
    if chat_id in _active:
        await message.reply_text("⏳ <b>A mass mention is already running.</b>\n<i>Use /cancel_all to stop it.</i>", parse_mode=_HTML)
        return

    custom = _extract_custom(message)
    reply_first = message.reply_to_message.id if message.reply_to_message else None

    # Admin/sender shown in the reply-mode broadcast card. Anonymous admins
    # post as the group itself (no from_user) — show the group title instead.
    if message.from_user is not None:
        sender = _mention(message.from_user) or f'<a href="tg://user?id={message.from_user.id}">admin</a>'
    else:
        sender = html.escape(getattr(message.sender_chat, "title", "") or "Admin")

    state = {"cancelled": False}
    _active[chat_id] = state
    state["task"] = asyncio.create_task(_run(client, chat_id, reply_first, custom, state, sender=sender))


@Client.on_message(filters.command("cancel_all"))
async def cancel_all_cmd(client, message):
    if message.chat.type not in _GROUPS:
        return
    if not await _allowed(client, message):
        await message.reply_text("🔒 <b>Admins only</b>", parse_mode=_HTML)
        return
    state = _active.get(message.chat.id)
    if not state:
        await message.reply_text("ℹ️ <b>No mass mention is running.</b>", parse_mode=_HTML)
        return
    state["cancelled"] = True
    await message.reply_text("✅ <b>Mass mention cancelled.</b>", parse_mode=_HTML)
