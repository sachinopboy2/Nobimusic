from pyrogram import Client, filters
from pyrogram.enums import MessageEntityType

from bot.client import userbot


@Client.on_message(filters.command("id"))
async def id_command(client, message):
    raw_text = message.text or ""

    for ent in (message.entities or []):
        if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
            u = ent.user
            text = (
                f"👤 User: {u.mention}\n"
                f"🆔 User ID: `{u.id}`\n"
                f"💬 Chat ID: `{message.chat.id}`"
            )
            await message.reply_text(text)
            return

    reply = message.reply_to_message

    if reply and reply.from_user:
        u = reply.from_user
        text = (
            f"👤 User: {u.mention}\n"
            f"🆔 User ID: `{u.id}`\n"
            f"💬 Chat ID: `{message.chat.id}`"
        )
        await message.reply_text(text)
        return

    if len(message.command) >= 2:
        raw = message.command[1].lstrip("@")
        try:
            if raw.isdigit():
                u = await client.get_users(int(raw))
            else:
                try:
                    u = await userbot.get_users(raw)
                except Exception:
                    u = await client.get_users(raw)
        except Exception as exc:
            await message.reply_text(f"❌ Couldn't resolve `{raw}`: {exc}")
            return
        text = (
            f"👤 User: {u.mention}\n"
            f"🆔 User ID: `{u.id}`\n"
            f"💬 Chat ID: `{message.chat.id}`"
        )
        await message.reply_text(text)
        return

    u = message.from_user
    text = (
        f"👤 User: {u.mention}\n"
        f"🆔 Your ID: `{u.id}`\n"
        f"💬 Chat ID: `{message.chat.id}`"
    )
    await message.reply_text(text)
