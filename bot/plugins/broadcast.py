"""/broadcast — owner-only fan-out of a message to every known chat.

Two forms:
  /broadcast <text>                  — sends the text to every chat
  reply to a message + /broadcast    — copies the replied message verbatim

In groups and supergroups, the sent message is pinned silently. DMs are
not pinned (Telegram allows it but users find it intrusive).

Chats are tracked as they message the bot — see bot/utils/chats.py. A
passive group=-1 handler in this module records every chat_id we see.
"""

import asyncio
import copy
import logging
import re

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.errors import (
    ChannelInvalid,
    ChannelPrivate,
    ChatAdminRequired,
    ChatWriteForbidden,
    FloodWait,
    PeerIdInvalid,
    UserIsBlocked,
    UserIsBot,
)

from bot.utils import chats
from bot.utils import emoji as e
from bot.utils.owner import get_owner_ids, is_sudo

logger = logging.getLogger("WarbornMusic.broadcast")

# Bots can comfortably do ~30 unique-target sends per second before
# Telegram throttles. 0.05s = 20/s, leaves headroom for retries.
_DELAY_BETWEEN_SENDS = 0.05


def _flood_seconds(exc: FloodWait) -> int:
    # pyrofork 2.x uses .value, older releases used .x. Cover both.
    return int(getattr(exc, "value", None) or getattr(exc, "x", 30))


def _has_inline_keyboard(markup) -> bool:
    """True iff `markup` is an inline keyboard (InlineKeyboardMarkup). Reply
    keyboards / ForceReply / ReplyKeyboardRemove expose no `.inline_keyboard`,
    so they fall through to the normal forward path unchanged."""
    return bool(getattr(markup, "inline_keyboard", None))


def _count_buttons(markup) -> int:
    return sum(len(row) for row in (getattr(markup, "inline_keyboard", None) or []))


# Inline-button authoring syntax for /broadcast. Lets an admin attach buttons
# that the BOT builds itself — guaranteed to render, with no dependence on being
# able to read a keyboard off some other message (which Telegram forbids for a
# bot on messages it didn't send). Widely-used "buttonurl" convention:
#   [Label](buttonurl://https://example.com)         -> URL button on a NEW row
#   [Label](buttonurl://https://example.com:same)    -> put it on the PREVIOUS row
_BUTTON_RE = re.compile(r"\[([^\[\]]+)\]\(buttonurl://(.+?)(:same)?\)", re.IGNORECASE)


def _shift_entities_out(entities, spans):
    """Return `entities` with the character ranges in `spans` (button-syntax
    removed from the text) taken out: entities fully inside a removed span are
    dropped, and every other entity's offset is shifted left by the amount of
    removed text before it. Keeps premium custom-emoji entities aligned."""
    out = []
    for ent in (entities or []):
        s, e = ent.offset, ent.offset + ent.length
        if any(rs <= s and e <= re_ for rs, re_ in spans):
            continue  # entity lived entirely inside a removed button definition
        removed_before = sum((re_ - rs) for rs, re_ in spans if re_ <= s)
        new = copy.copy(ent)
        new.offset = s - removed_before
        if new.offset < 0 or new.length <= 0:
            continue
        out.append(new)
    return out


def _parse_button_markup(text, entities):
    """Pull [Label](buttonurl://URL[:same]) definitions out of `text`.

    Returns (clean_text, clean_entities, markup_or_None): the button definitions
    are removed from the visible text, remaining entities are offset-shifted to
    stay aligned, and the buttons become an InlineKeyboardMarkup (URL buttons —
    the safe, universal type; ':same' keeps a button on the previous row).
    Never raises: on any parse issue it returns the text unchanged, markup=None,
    so a normal /broadcast is completely unaffected."""
    try:
        matches = list(_BUTTON_RE.finditer(text or ""))
        if not matches:
            return text, entities, None
        rows, parts, spans, last = [], [], [], 0
        for m in matches:
            parts.append(text[last:m.start()])
            spans.append((m.start(), m.end()))
            last = m.end()
            btn = InlineKeyboardButton(m.group(1).strip(), url=m.group(2).strip())
            if m.group(3) and rows:  # ':same' → same row as the previous button
                rows[-1].append(btn)
            else:
                rows.append([btn])
        parts.append(text[last:])
        clean_text = "".join(parts)
        clean_entities = _shift_entities_out(entities, spans)

        # Trim trailing whitespace left where buttons were removed, clamping any
        # entity that ran into the trimmed tail (offsets before the cut are safe).
        stripped = clean_text.rstrip()
        if len(stripped) < len(clean_text):
            cut, kept = len(stripped), []
            for ent in clean_entities:
                if ent.offset >= cut:
                    continue
                if ent.offset + ent.length > cut:
                    ent.length = cut - ent.offset
                if ent.length > 0:
                    kept.append(ent)
            clean_text, clean_entities = stripped, kept

        markup = InlineKeyboardMarkup(rows) if rows else None
        return clean_text, clean_entities, markup
    except Exception as exc:
        logger.info("broadcast: button-syntax parse failed (%s: %s) — ignoring",
                    type(exc).__name__, exc)
        return text, entities, None


def _shift_entities_for_body(message, body_start: int):
    """Return a list of MessageEntity objects shifted so they line up with
    `message.text[body_start:]`. Entities entirely in the stripped prefix
    are dropped; entities that straddle the split are clamped.

    Used so `/broadcast <text-with-premium-emoji>` keeps the premium-emoji
    entities — pyrofork's `send_message(text=str)` without an `entities=`
    argument re-parses through whatever parse_mode is set and never re-emits
    custom-emoji entities, which is why the visible glyph reverts to its
    fallback character.
    """
    # Deep-copy each entity so we don't mutate state held on the original
    # incoming Message (which other handlers may also read).
    import copy

    out = []
    for ent in (message.entities or []):
        ent_end = ent.offset + ent.length
        if ent_end <= body_start:
            continue
        new = copy.copy(ent)
        if ent.offset < body_start:
            new.length = ent.length - (body_start - ent.offset)
            new.offset = 0
        else:
            new.offset = ent.offset - body_start
        if new.length <= 0:
            continue
        out.append(new)
    return out


async def _send_one(client, chat_id: int, *, reply, body: str, body_entities, markup=None):
    """Returns (sent_message, error_class_name_or_None).

    Replied-message broadcasts are delivered with a NATIVE Telegram forward
    (client.forward_messages, no hide_sender_name/drop_author) — exactly how a
    normal forward behaves. Telegram carries the message across server-side, so
    the media, caption, formatting, entities, the "Forwarded from …" header, and
    the inline keyboard (reply_markup) are all preserved as-is, with nothing
    reconstructed. NOTE: the previous hide_sender_name=True variant turned the
    forward into a copy, which is what stripped the inline keyboard — a plain
    forward keeps it.

    For text-mode broadcasts (`/broadcast <text>`, no reply) we pass
    `entities=...` explicitly so the caller-extracted (and offset-shifted)
    custom-emoji entities are kept on the wire instead of being re-parsed away,
    plus any inline keyboard the admin authored via the buttonurl:// syntax.
    """
    if reply is not None:
        forwarded = await client.forward_messages(
            chat_id=chat_id,
            from_chat_id=reply.chat.id,
            message_ids=reply.id,
            disable_notification=True,
        )
        result = forwarded[0] if isinstance(forwarded, list) else forwarded
        return result, None
    sent = await client.send_message(
        chat_id,
        body,
        entities=body_entities or None,
        reply_markup=markup if _has_inline_keyboard(markup) else None,
    )
    return sent, None


async def _maybe_pin(client, message) -> bool:
    """Pin silently if the destination is a group/supergroup. Returns
    True on a successful pin, False otherwise (including non-group
    chats — they intentionally aren't pinned).
    """
    if message is None or message.chat is None:
        return False
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return False
    try:
        await client.pin_chat_message(
            chat_id=message.chat.id,
            message_id=message.id,
            disable_notification=True,
        )
        return True
    except ChatAdminRequired:
        logger.info("Skip pin in %s: not admin", message.chat.id)
    except Exception as exc:
        logger.info("Pin failed in %s: %s", message.chat.id, exc)
    return False


@Client.on_message(filters.command("broadcast"))
async def broadcast_command(client, message):
    if not message.from_user:
        return
    if not await is_sudo(message.from_user.id):
        owners = await get_owner_ids()
        await message.reply_text(
            f"🔒 {e.SHIELD} <b>Sudo only</b>\n\n"
            f"<b>Your ID:</b> <code>{message.from_user.id}</code>\n"
            f"<b>Owner(s):</b> <code>{', '.join(str(i) for i in sorted(owners)) or '(none)'}</code>\n\n"
            "<i>Owner can grant access with /addsudo, or set OWNER_ID/SUDO_USERS in .env.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    reply = message.reply_to_message

    # Pull the body text + entities directly off the original message so
    # premium custom-emoji entities are preserved. Use `message.text` minus
    # the "/broadcast " prefix rather than `message.command[1:]` (which
    # strips entity offsets entirely).
    body_text = ""
    body_entities = []
    if message.text and len(message.command) > 1:
        # The body begins after the first whitespace following the command.
        raw = str(message.text)
        space = raw.find(" ")
        if space != -1:
            body_text = raw[space + 1 :]
            body_entities = _shift_entities_for_body(message, space + 1)

    # Extract any inline-button definitions the admin typed into the command
    # ([Label](buttonurl://URL[:same])). These are removed from the visible text
    # and become a keyboard the bot builds itself — the guaranteed way to
    # broadcast buttons regardless of whether a replied message's keyboard is
    # readable. No button syntax → text/entities returned unchanged.
    typed_markup = None
    if body_text:
        body_text, body_entities, typed_markup = _parse_button_markup(body_text, body_entities)

    if reply is None and not body_text:
        await message.reply_text(
            f"{e.MEGA} <b>Broadcast — how to use</b>\n"
            "• <code>/broadcast &lt;text&gt;</code> — <i>send to every known chat</i>\n"
            "• <i>Reply to a message with</i> <code>/broadcast</code> — <i>copy it verbatim (keeps its inline buttons)</i>\n"
            "• <i>Add buttons yourself:</i> <code>/broadcast Hi! [Join](buttonurl://https://t.me/yourchat)</code>\n"
            "   <i>— use</i> <code>:same</code> <i>before the closing</i> <code>)</code> <i>to put a button on the same row.</i>\n\n"
            "<i>Groups: pinned silently. DMs: sent, not pinned.</i>",
            parse_mode=ParseMode.HTML)
        return

    targets = chats.all_chats()
    if not targets:
        await message.reply_text(
            "📭 <b>No known chats yet</b>\n"
            "<i>The bot learns chats as it sees messages — let it run a bit, or "
            "have a user DM it / message a group it's in.</i>",
            parse_mode=ParseMode.HTML)
        return

    # Reply broadcasts are delivered by a NATIVE forward (see _send_one), which
    # preserves the replied message's own inline keyboard server-side — no
    # reading/reconstruction needed. `reply_markup` here only applies to the
    # text-mode (`/broadcast <text>`) path, where the admin can author buttons
    # with the buttonurl:// syntax.
    reply_markup = typed_markup if reply is None else None
    logger.info("broadcast: starting — reply=%s, %d authored button(s) on text path",
                reply is not None, _count_buttons(reply_markup))

    n_dms = sum(1 for c in targets if c > 0)
    n_groups = len(targets) - n_dms
    status = await message.reply_text(
        f"{e.MEGA} <b>Broadcasting…</b>\n"
        f"<i>{len(targets)} chat(s) — {n_groups} group(s) + {n_dms} DM(s)</i>",
        parse_mode=ParseMode.HTML)

    sent = 0
    sent_dms = 0
    sent_groups = 0
    pinned = 0
    failed = 0
    forgotten = 0

    for chat_id in targets:
        kind = "DM" if chat_id > 0 else "group"
        try:
            bcast, _ = await _send_one(
                client, chat_id, reply=reply, body=body_text,
                body_entities=body_entities, markup=reply_markup,
            )
            sent += 1
            if chat_id > 0:
                sent_dms += 1
            else:
                sent_groups += 1
            logger.info("broadcast → %s %s OK", kind, chat_id)
            if await _maybe_pin(client, bcast):
                pinned += 1
        except FloodWait as fw:
            wait = _flood_seconds(fw)
            logger.warning(
                "FloodWait %ss while broadcasting to %s — sleeping then retrying",
                wait, chat_id,
            )
            await asyncio.sleep(wait + 1)
            try:
                bcast, _ = await _send_one(
                    client, chat_id, reply=reply, body=body_text,
                    body_entities=body_entities, markup=reply_markup,
                )
                sent += 1
                if await _maybe_pin(client, bcast):
                    pinned += 1
            except Exception as exc2:
                failed += 1
                logger.info("Retry-after-flood failed for %s: %s", chat_id, exc2)
        except (
            PeerIdInvalid,
            UserIsBlocked,
            UserIsBot,
            ChannelInvalid,
        ) as exc:
            # Permanently dead: bot was kicked, user blocked us, chat or
            # channel id no longer resolves. Drop from registry.
            forgotten += 1
            chats.forget(chat_id)
            logger.info("Forgetting %s: %s: %s", chat_id, type(exc).__name__, exc)
        except (ChatWriteForbidden, ChannelPrivate) as exc:
            # Recoverable: bot lost write/pin permission in this chat, or
            # the channel is currently private/admin-only. Keep the chat
            # in the registry so the next broadcast tries again once
            # permissions are restored.
            failed += 1
            logger.info(
                "Broadcast to %s blocked (kept in registry): %s: %s",
                chat_id, type(exc).__name__, exc,
            )
        except Exception as exc:
            failed += 1
            logger.info("Broadcast to %s failed: %s: %s", chat_id, type(exc).__name__, exc)

        await asyncio.sleep(_DELAY_BETWEEN_SENDS)

    summary = (
        f"{e.MEGA} <b>Broadcast complete</b>\n\n"
        f"✅ <b>Sent:</b> {sent}  <i>({sent_groups} group(s), {sent_dms} DM(s))</i>\n"
        f"📌 <b>Pinned:</b> {pinned}\n"
        f"❌ <b>Failed:</b> {failed}\n"
        f"🗑️ <b>Forgotten (kicked/blocked/dead):</b> {forgotten}"
    )
    try:
        await status.edit_text(summary, parse_mode=ParseMode.HTML)
    except Exception:
        await message.reply_text(summary, parse_mode=ParseMode.HTML)


# Track the bot's OWN membership changes — fires when the bot is added to
# a group, removed, promoted, or restricted. Registers the chat on join,
# drops it on leave. Future-proofs the broadcast registry against the
# /broadcast-only-hits-my-DM symptom.
_PRESENT = (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
_GONE = (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)


@Client.on_chat_member_updated()
async def _track_self_membership(client, update):
    new = getattr(update, "new_chat_member", None)
    if new is None or new.user is None:
        return
    if not getattr(new.user, "is_self", False):
        # Some other member changed — not our concern; welcome.py handles that.
        return
    chat_id = update.chat.id if update.chat else None
    if chat_id is None:
        return
    if new.status in _PRESENT:
        if chats.remember(chat_id):
            logger.info("self added to chat %s (status=%s)", chat_id, new.status)
    elif new.status in _GONE:
        if chats.forget(chat_id):
            logger.info("self removed from chat %s (status=%s)", chat_id, new.status)


# Passive: record every chat the bot sees a message in. group=-1 runs
# before the command handlers in group=0 but doesn't consume the message
# — different groups all fire independently.
@Client.on_message(filters.all, group=-1)
async def _track_chat(client, message):
    chat = message.chat
    user = message.from_user
    try:
        text = (message.text or message.caption or "")[:60]
    except Exception:
        logger.exception("Failed to read message text")
        text = "<error>"
    logger.info(
        "saw msg in chat=%s (type=%s) from user=%s (id=%s) text=%r",
        chat.id if chat else None,
        chat.type.value if chat and chat.type else None,
        user.username if user else None,
        user.id if user else None,
        text,
    )
    if chat is not None:
        added = chats.remember(chat.id)
        if added:
            logger.info("registered new chat %s in registry", chat.id)
