"""/seeddm — owner-only command to manually add user IDs to the broadcast
chat registry.

Bots can't enumerate users who've started them — there's no Telegram API
for that. So if you know specific user IDs that have already /started the
bot, you can seed them here and /broadcast will include their DMs.

Usage:
  /seeddm 123456789 987654321 ...
  (reply to a forwarded message from the user) /seeddm

The user MUST have already done /start with the bot — Telegram bots can't
initiate conversations with strangers, so seeding a user who hasn't
started the bot just produces a "Forbidden: bot can't initiate
conversation" error during /broadcast (and we'll auto-drop them).
"""

import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from bot.utils import chats
from bot.utils import emoji as e
from bot.utils.owner import is_sudo

logger = logging.getLogger("WarbornMusic.seeddm")

_HTML = ParseMode.HTML


def _parse_ids_from_args(args) -> list[int]:
    out = []
    for a in args:
        a = a.strip().lstrip("@")
        if a.lstrip("-").isdigit():
            out.append(int(a))
    return out


@Client.on_message(filters.command("seeddm"))
async def seeddm_command(client, message):
    if not message.from_user or not await is_sudo(message.from_user.id):
        await message.reply_text(
            f"🔒 {e.SHIELD} <b>Sudo only</b>\n"
            "<i>/seeddm is for sudo users.</i>", parse_mode=_HTML)
        return

    ids: list[int] = []

    # Mode 1: reply to a forwarded message — pick up forward_from.id.
    reply = message.reply_to_message
    if reply is not None:
        fwd = getattr(reply, "forward_from", None)
        if fwd is not None and getattr(fwd, "id", None):
            ids.append(fwd.id)
        elif reply.from_user is not None:
            ids.append(reply.from_user.id)

    # Mode 2: positional args.
    if len(message.command) > 1:
        ids.extend(_parse_ids_from_args(message.command[1:]))

    if not ids:
        await message.reply_text(
            f"{e.MEGA} <b>Seed DMs — how to use</b>\n"
            "• <code>/seeddm 123 456 789</code> — <i>seed by user ID(s)</i>\n"
            "• <i>Reply to a forwarded message with</i> <code>/seeddm</code>\n\n"
            "<i>The user must have already started the bot — un-started seeds are "
            "auto-dropped on the next failed broadcast.</i>", parse_mode=_HTML)
        return

    added = 0
    skipped = 0
    for uid in ids:
        if chats.remember(uid):
            added += 1
            logger.info("/seeddm: added user %s to registry", uid)
        else:
            skipped += 1

    await message.reply_text(
        f"{e.MEGA} <b>Seeded</b>\n\n"
        f"✅ <b>Added:</b> {added}\n"
        f"➖ <b>Already known:</b> {skipped}\n"
        f"📊 <b>Registry size:</b> {chats.count()}", parse_mode=_HTML)
