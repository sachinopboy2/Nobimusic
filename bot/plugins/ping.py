import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

logger = logging.getLogger("WarbornMusic.ping")

# Pyrofork's HTML parser uses <emoji id="..."> not <tg-emoji emoji-id="...">.
# The text inside the tag (here: 🏓) is the fallback shown to Telegram
# clients that don't support custom emoji.
_PONG_REPLY = '<emoji id="4958845510543737828">🏓</emoji> Pong!'


@Client.on_message(filters.command("ping"))
async def ping_command(client, message):
    logger.info(
        "ping_command fired in chat=%s by user=%s",
        message.chat.id if message.chat else None,
        message.from_user.id if message.from_user else None,
    )
    await message.reply_text(_PONG_REPLY, parse_mode=ParseMode.HTML)
