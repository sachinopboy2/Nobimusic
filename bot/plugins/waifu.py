"""/waifu — assigns a random group member as the sender's waifu for 24h.

Fully isolated: registers its own command, uses only bot.utils.waifu for state
and rendering, and never touches other commands, handlers or stores. Every
failure is contained so /waifu can never crash the bot or affect other commands.
"""

import logging
import random
import time

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode

from bot.utils import waifu

logger = logging.getLogger("WarbornMusic.waifu")
_HTML = ParseMode.HTML
_GROUPS = (ChatType.GROUP, ChatType.SUPERGROUP)


def _display_name(user) -> str:
    name = " ".join(p for p in (getattr(user, "first_name", ""),
                                getattr(user, "last_name", "")) if p).strip()
    return name or "Unknown"


async def _pick_waifu(client, chat_id):
    """Uniformly pick one eligible member (sender included). O(members) API
    paging, O(1) extra memory via reservoir sampling — scales to large groups."""
    chosen, n = None, 0
    async for m in client.get_chat_members(chat_id):
        u = getattr(m, "user", None)
        if not waifu.is_eligible(u):
            continue
        n += 1
        if random.random() < 1.0 / n:  # k=1 reservoir: every member equally likely
            chosen = u
    return chosen


async def _photo_id(client, user_id):
    try:
        async for p in client.get_chat_photos(user_id, limit=1):
            return getattr(p, "file_id", None)
    except Exception:
        pass
    return None


async def _send_card(client, chat_id, photo_id, caption):
    """Send the card as a standalone photo message (never a reply). Falls back
    to the bundled image, then to text-only, so a bad file_id never fails."""
    for photo in (photo_id, waifu.fallback_image()):
        if not photo:
            continue
        try:
            await client.send_photo(chat_id, photo, caption=caption, parse_mode=_HTML)
            return
        except Exception as exc:
            logger.warning("waifu: send_photo failed (%s) — trying fallback", exc)
    await client.send_message(chat_id, caption, parse_mode=_HTML)


@Client.on_message(filters.command("waifu"))
async def waifu_command(client, message):
    chat = message.chat
    try:
        if not chat or chat.type not in _GROUPS:
            await client.send_message(chat.id, "This command can only be used inside groups.")
            return
        sender = message.from_user
        if not sender:
            return  # anonymous admin / channel post — nothing to bond
        now = time.time()
        owner = waifu.mention(sender.id, _display_name(sender))

        profile = waifu.get_profile(sender.id, chat.id)
        if profile and waifu.is_active(profile, now):
            # Active bond: re-show the exact stored card, headed by its owner.
            caption = waifu.owner_header(owner) + waifu.render_card(profile)
            await _send_card(client, chat.id, profile.get("photo_id"), caption)
            return

        target = await _pick_waifu(client, chat.id)
        if target is None:
            await client.send_message(chat.id, "🌸 Couldn't find anyone to match you with right now. Try again later.")
            return

        photo_id = await _photo_id(client, target.id)
        profile = {
            "chat_id": chat.id,
            "waifu_id": target.id,
            "waifu_name": _display_name(target),
            "waifu_username": getattr(target, "username", None),
            "assigned_at": now,
            "photo_id": photo_id,
            **waifu.new_profile_values(),
        }
        waifu.put_profile(sender.id, chat.id, profile)

        caption = waifu.owner_header(owner) + waifu.render_card(profile) + waifu.footer_new()
        await _send_card(client, chat.id, photo_id, caption)
    except Exception:
        logger.exception("waifu_command failed")
        try:
            await client.send_message(chat.id, "🌸 Something went wrong. Please try again in a moment.")
        except Exception:
            pass
