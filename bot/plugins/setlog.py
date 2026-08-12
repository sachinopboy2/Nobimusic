"""/setlog — owner/sudo command that marks the current chat as the log
destination (replaces any previous one; persisted across restarts).
Also hosts the "bot was added to a chat" logger.
"""

import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from bot.utils import emoji as e
from bot.utils.logchannel import (
    clear_log_chat,
    get_log_chat,
    log_bot_added,
    set_log_chat,
)
from bot.utils.owner import is_owner, is_sudo

logger = logging.getLogger("WarbornMusic.setlog")

_HTML = ParseMode.HTML


async def _allowed(message) -> bool:
    uid = message.from_user.id if message.from_user else None
    if uid is not None:
        return await is_owner(uid) or await is_sudo(uid)
    # Channel post / anonymous admin: no from_user to check. Accept
    # only when the sender IS the chat itself (i.e. posted by an
    # admin of this very channel/group).
    return (
        message.sender_chat is not None
        and message.chat is not None
        and message.sender_chat.id == message.chat.id
    )


@Client.on_message(filters.command("setlog"))
async def setlog_command(client, message):
    if not await _allowed(message):
        await message.reply_text(
            f"🔒 {e.SHIELD} <b>Owner & sudo only</b>", parse_mode=_HTML)
        return

    set_log_chat(message.chat.id)
    logger.info("log chat set to %s by user=%s",
                message.chat.id, message.from_user.id if message.from_user else None)
    await message.reply_text(
        f'{e.GEAR} <b>Log channel set</b>\n'
        "<i>All future bot logs will be sent here.</i>",
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(filters.command(["removelog", "remlog", "unsetlog"]))
async def removelog_command(client, message):
    if not await _allowed(message):
        await message.reply_text(
            f"🔒 {e.SHIELD} <b>Owner & sudo only</b>", parse_mode=_HTML)
        return

    previous = get_log_chat()
    had = clear_log_chat()
    logger.info("log chat cleared (was %s) by user=%s",
                previous, message.from_user.id if message.from_user else None)
    if had:
        await message.reply_text(
            f'{e.GEAR} <b>Log channel removed</b>\n'
            "<i>Bot logs are disabled until /setlog is used again.</i>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.reply_text(
            "ℹ️ <b>No log channel was configured.</b>", parse_mode=_HTML)


@Client.on_message(filters.new_chat_members & filters.group, group=3)
async def _bot_added_logger(client, message):
    try:
        me = await client.get_me()
        if any(u.id == me.id for u in (message.new_chat_members or [])):
            await log_bot_added(client, message.chat, message.from_user)
    except Exception:
        logger.exception("bot-added log failed")
