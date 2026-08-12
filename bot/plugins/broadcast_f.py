"""/broadcast_F — owner-only NATIVE forward of a replied message to every
known chat.

Sibling of /broadcast (bot/plugins/broadcast.py), which it deliberately does
NOT modify. The only difference is the send method:

  /broadcast   (reply) → forward_messages(hide_sender_name=True) — Telegram
                         sends a copy, so a forwarded POLL becomes a brand-new
                         poll in each destination and votes split.
  /broadcast_F (reply) → forward_messages() with the sender header intact — a
                         genuine native forward, so a poll stays the SAME
                         message and its results/votes stay linked.

Reuses the existing permission system, chat registry, pin behaviour, FloodWait
handling, logging, and summary format from broadcast.py.
"""

import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    ChannelInvalid,
    ChannelPrivate,
    ChatWriteForbidden,
    FloodWait,
    PeerIdInvalid,
    UserIsBlocked,
    UserIsBot,
)

from bot.plugins.broadcast import _DELAY_BETWEEN_SENDS, _flood_seconds, _maybe_pin
from bot.utils import chats
from bot.utils import emoji as e
from bot.utils.owner import get_owner_ids, is_sudo

logger = logging.getLogger("WarbornMusic.broadcast_f")


async def _forward_one(client, chat_id: int, *, reply):
    """Native forward (sender header kept) — no hide_sender_name, so polls and
    other forwardable types stay the same Telegram message. Returns the sent
    Message."""
    forwarded = await client.forward_messages(
        chat_id=chat_id,
        from_chat_id=reply.chat.id,
        message_ids=reply.id,
        disable_notification=True,
    )
    return forwarded[0] if isinstance(forwarded, list) else forwarded


@Client.on_message(filters.command("broadcast_F"))
async def broadcast_forward_command(client, message):
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
    if reply is None:
        await message.reply_text(
            f"{e.MEGA} <b>Forward-broadcast — how to use</b>\n"
            "• <i>Reply to any message with</i> <code>/broadcast_F</code>\n\n"
            "<i>Forwards the exact original message (keeps poll votes linked) to "
            "every known chat. For copy-style broadcasts use</i> <code>/broadcast</code><i>.</i>",
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

    n_dms = sum(1 for c in targets if c > 0)
    n_groups = len(targets) - n_dms
    status = await message.reply_text(
        f"{e.MEGA} <b>Forwarding…</b>\n"
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
            bcast = await _forward_one(client, chat_id, reply=reply)
            sent += 1
            if chat_id > 0:
                sent_dms += 1
            else:
                sent_groups += 1
            logger.info("broadcast_F → %s %s OK", kind, chat_id)
            if await _maybe_pin(client, bcast):
                pinned += 1
        except FloodWait as fw:
            wait = _flood_seconds(fw)
            logger.warning(
                "FloodWait %ss while forward-broadcasting to %s — sleeping then retrying",
                wait, chat_id,
            )
            await asyncio.sleep(wait + 1)
            try:
                bcast = await _forward_one(client, chat_id, reply=reply)
                sent += 1
                if chat_id > 0:
                    sent_dms += 1
                else:
                    sent_groups += 1
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
            forgotten += 1
            chats.forget(chat_id)
            logger.info("Forgetting %s: %s: %s", chat_id, type(exc).__name__, exc)
        except (ChatWriteForbidden, ChannelPrivate) as exc:
            failed += 1
            logger.info(
                "Forward-broadcast to %s blocked (kept in registry): %s: %s",
                chat_id, type(exc).__name__, exc,
            )
        except Exception as exc:
            failed += 1
            logger.info("Forward-broadcast to %s failed: %s: %s", chat_id, type(exc).__name__, exc)

        await asyncio.sleep(_DELAY_BETWEEN_SENDS)

    summary = (
        f"{e.MEGA} <b>Forward-broadcast complete</b>\n\n"
        f"✅ <b>Sent:</b> {sent}  <i>({sent_groups} group(s), {sent_dms} DM(s))</i>\n"
        f"📌 <b>Pinned:</b> {pinned}\n"
        f"❌ <b>Failed:</b> {failed}\n"
        f"🗑️ <b>Forgotten (kicked/blocked/dead):</b> {forgotten}"
    )
    try:
        await status.edit_text(summary, parse_mode=ParseMode.HTML)
    except Exception:
        await message.reply_text(summary, parse_mode=ParseMode.HTML)
