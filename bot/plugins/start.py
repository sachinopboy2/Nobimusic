"""/start — premium custom-emoji welcome card."""
from pyrogram import Client, filters
from pyrogram.enums import ButtonStyle, ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot.config import (
    BOT_NAME, BOT_USERNAME, OWNER_URL, START_IMAGE,
    SUPPORT_CHAT, UPDATE_CHANNEL, normalize_link,
)
from bot.utils import emoji as e

def _start_caption(user) -> str:
    mention = e.mention(user)
    return (
        f"✦  <b>Welcome to {BOT_NAME}</b> {e.NOTE}\n\n"
        f"Hey {mention}!\n"
        f"I'm {BOT_NAME}, your music companion for Telegram voice chats.\n\n"
        f"{e.BOLT} Fast  •  {e.MUSIC} High-quality audio\n"
        f"{e.BRAIN} Smart queue  •  {e.FIRE} Powerful playback\n"
        f"{e.PEOPLE} Group friendly  •  {e.HEAD} 24/7 music\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"{e.USER} <b>Your Profile</b>\n"
        f"❤️‍🔥 User: {mention}\n"
        f"{e.IDCARD} ID: <code>{user.id}</code>\n\n"
        "Use /help to view all available commands."
    )

async def _resolve_add_url(client) -> str:
    username = BOT_USERNAME
    if not username:
        try:
            me = await client.get_me()
            username = me.username or ""
        except Exception:
            username = ""
    return f"https://t.me/{username}?startgroup=true" if username else ""

async def _start_keyboard(client, styled=True):
    rows = []
    updates_url = normalize_link(UPDATE_CHANNEL)
    support_url = normalize_link(SUPPORT_CHAT)
    owner_url = normalize_link(OWNER_URL)

    def add(label, url=None, callback_data=None, emoji_id=None, style=None):
        kw = {"url": url} if url else {"callback_data": callback_data}
        if styled:
            if emoji_id:
                kw["icon_custom_emoji_id"] = emoji_id
            if style:
                kw["style"] = style
        return InlineKeyboardButton(label, **kw)

    top = []
    if updates_url:
        top.append(add("Updates" if styled else "📢 Updates",
                       url=updates_url, emoji_id=e.MEGA_ID, style=ButtonStyle.PRIMARY))
    if support_url:
        top.append(add("Support" if styled else "💬 Support",
                       url=support_url, emoji_id=e.CHAT_ID, style=ButtonStyle.SUCCESS))
    if top:
        rows.append(top)

    if owner_url:
        rows.append([add("Owner" if styled else "👑 Owner",
                         url=owner_url, emoji_id=e.CROWN_ID, style=ButtonStyle.PRIMARY)])

    add_url = await _resolve_add_url(client)
    if add_url:
        rows.append([add("Add Me to Your Group" if styled else "➕ Add Me to Your Group",
                         url=add_url, emoji_id=e.PLUS_ID, style=ButtonStyle.SUCCESS)])

    rows.append([add("Help & Commands" if styled else "📚 Help & Commands",
                     callback_data="help:0:home", emoji_id=e.BOOK_ID,
                     style=ButtonStyle.PRIMARY)])
    return InlineKeyboardMarkup(rows)

async def _safe_start_keyboard(client):
    try:
        return await _start_keyboard(client, True)
    except Exception:
        return await _start_keyboard(client, False)

@Client.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    from bot.utils.logchannel import log_bot_started
    await log_bot_started(client, message.from_user)
    await message.reply_photo(
        photo=START_IMAGE,
        caption=_start_caption(message.from_user),
        parse_mode=ParseMode.HTML,
        reply_markup=await _safe_start_keyboard(client),
    )

@Client.on_callback_query(filters.regex(r"^start:home$"))
async def start_home_callback(client, callback_query):
    try:
        await callback_query.edit_message_caption(
            caption=_start_caption(callback_query.from_user),
            parse_mode=ParseMode.HTML,
            reply_markup=await _safe_start_keyboard(client),
        )
    except Exception as exc:
        if "MESSAGE_NOT_MODIFIED" in str(exc).upper():
            await callback_query.answer()
            return
        await callback_query.answer(f"Update failed: {exc}", show_alert=True)
        return
    await callback_query.answer()
