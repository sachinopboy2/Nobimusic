"""/help — paginated. Same banner photo stays in place; navigation
buttons swap the caption between pages.

Each page must fit Telegram's 1024-char media-caption limit. The
constructor below adds a small header line (page title + page
indicator) on top of the section body, so when adding/changing pages
keep the body shorter than ~950 chars to leave room for that.
"""

from pyrogram import Client, filters
from pyrogram.enums import ButtonStyle, ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Banner image and display name come from config (driven by .env).
from bot.config import BOT_NAME, HELP_IMAGE
from bot.utils import emoji as e

# Each page = (short title shown in the header, full HTML body).
# Bodies use the centralized premium-emoji snippets from bot.utils.emoji
HELP_PAGES: list[tuple[str, str]] = [
    (
        "Music",
        f"{e.MUSIC} <b>Music</b>\n"
        f"{e.MUSIC} /play - Play a song\n"
        f"{e.HEAD} /vplay (alias /cplay) - Play a video in voice chat\n"
        f"{e.MUSIC} /song - Search and download a song\n"
        f"{e.HEAD} /video - Search and download a video\n"
        f"{e.NOTE} /pause - Pause playback\n"
        f"{e.MUSIC} /resume - Resume playback\n"
        f"{e.BOLT} /skip - Skip the current track\n"
        f"{e.BOLT} /vskip - Skip the current video\n"
        f"{e.NO_ENTRY} /stop (alias /end) - Stop playback\n"
        f"{e.INBOX} /queue - Show the music queue\n"
        f"{e.BLOCK} /clearqueue (aliases /cq /clearall) - Clear the queue",
    ),
    (
        "Moderation",
        f"{e.SHIELD} <b>Moderation</b>\n"
        f"{e.BLOCK} /ban - Ban a user in this chat\n"
        f"{e.CHECK} /unban - Unban a user in this chat\n"
        f"{e.BOMB1} /gban - (sudo) global ban across every chat the bot is in\n"
        f"{e.CHECK} /removegban (aliases /ungban /delgban) - (sudo) lift a global ban\n"
        f"{e.CROWN} /promote (alias /feature) - Promote a user to admin\n"
        f"{e.THUMBS_DOWN} /demote (alias /unpromote) - Remove a user's admin rights\n"
        f"{e.PIN} /pin - Pin a replied message (add 'loud' to notify)\n"
        f"{e.NO_ENTRY} /unpin - Unpin a replied (or the latest) message\n"
        f"{e.BLOCK} /unpinall confirm - Clear all pins\n"
        f"{e.FIRE} /purge - Reply: delete up to here. /purge n: last n. "
        "/purge n min: last n minutes (max 200, &lt;48h only)\n"
        f"{e.PEOPLE} /all - Tag everyone in batches. Reply to a message to tag alongside "
        "it; add text (formatting &amp; premium emoji preserved). /cancel_all stops it",
    ),
    (
        "General",
        f"{e.WAVE} <b>Welcome &amp; Greetings</b>\n"
        f"{e.WAVE} /greetings on|off - Toggle welcome cards on member join\n"
        f"{e.GHOST} /departure on|off (alias /farewell) - Toggle farewell messages on member leave\n\n"
        f"{e.INBOX} <b>Auto-download</b>\n"
        "Paste a YouTube or Pinterest link in any chat — I'll fetch the video and post it back.\n\n"
        f"{e.IDCARD} <b>Information</b>\n"
        f"{e.IDCARD} /id - Get user, group, or chat ID\n\n"
        f"{e.GEAR} <b>General</b>\n"
        f"{e.STAR} /start - Show the welcome message\n"
        f"{e.BOOK} /help - Show this help menu\n"
        f"{e.BOLT} /ping - Check if the bot is online",
    ),
    (
        "Fun",
        f"{e.DICE} <b>Fun</b>\n"
        f"{e.HEART_EYES} /waifu - Match with a random group member as your waifu for 24h\n"
        f"{e.DICE} /toss - Toss a coin\n"
        f"{e.BOMB1} /kill (alias /murder) - Attempt to kill another user (50/50 outcome)\n"
        f"{e.TEDDY} /pat (alias /headpat) - Give someone a wholesome headpat\n"
        f"{e.SPARKLE} /aura - Check someone's aura level (0-100)\n"
        f"{e.CHEERS} /celebrate &lt;occasion&gt; - bday/anniversary/promotion/win/welcome-back",
    ),
    (
        "Sudo",
        f"{e.CROWN} <b>Sudo</b>\n"
        f"{e.SEARCH} /stats - (sudo) bot stats and version info\n"
        f"{e.COMET} /refresh - (sudo) probe &amp; rotate YouTube cookie jars, report health\n"
        f"{e.MEGA} /broadcast - (sudo) push a message to every chat\n"
        f"{e.PEOPLE} /seeddm - (sudo) seed user IDs into the broadcast registry\n"
        f"{e.BLOCK} /blist - (sudo) ignore every message from a user\n"
        f"{e.CHECK} /unblist (alias /removeblist) - (sudo) remove a user from the blacklist\n"
        f"{e.CROWN} /addsudo - (owner) grant sudo to a user\n"
        f"{e.THUMBS_DOWN} /delsudo (aliases /removesudo /rmsudo) - (owner) revoke sudo\n"
        f"{e.EYES} /sudolist (alias /sudoers) - (sudo) list current sudoers\n"
        f"{e.PIN} /setlog - (owner/sudo) make this chat the log channel for "
        "start/add/download events\n"
        f"{e.NO_ENTRY} /removelog (aliases /remlog /unsetlog) - (owner/sudo) disable logging",
    ),
]

NUM_PAGES = len(HELP_PAGES)


def _build_caption(index: int) -> str:
    title, body = HELP_PAGES[index]
    return (
        f"{e.NOTE} <b>{BOT_NAME}</b>  "
        f"<i>· page {index + 1}/{NUM_PAGES} · {title}</i>\n\n"
        f"{body}"
    )


def _build_keyboard(index: int, home: bool = False) -> InlineKeyboardMarkup:
    prev_idx = (index - 1) % NUM_PAGES
    next_idx = (index + 1) % NUM_PAGES
    sfx = ":home" if home else ""

    rows = [
        [
            InlineKeyboardButton("Prev", callback_data=f"help:{prev_idx}{sfx}",
                                 icon_custom_emoji_id=e.NOTE_ID,
                                 style=ButtonStyle.PRIMARY),
            InlineKeyboardButton(f"{index + 1}/{NUM_PAGES}", callback_data="help:noop",
                                 style=ButtonStyle.DEFAULT),
            InlineKeyboardButton("Next", callback_data=f"help:{next_idx}{sfx}",
                                 icon_custom_emoji_id=e.BOLT_ID,
                                 style=ButtonStyle.PRIMARY),
        ]
    ]
    if home:
        rows.append([
            InlineKeyboardButton("Back", callback_data="start:home",
                                 icon_custom_emoji_id=e.CROWN_ID,
                                 style=ButtonStyle.SUCCESS)
        ])
    return InlineKeyboardMarkup(rows)


@Client.on_message(filters.command("help"))
async def help_command(client, message):
    await message.reply_photo(
        photo=HELP_IMAGE,
        caption=_build_caption(0),
        parse_mode=ParseMode.HTML,
        reply_markup=_build_keyboard(0),
    )


@Client.on_callback_query(filters.regex(r"^help:(?:noop|\d+)(?::home)?$"))
async def help_page_callback(client, callback_query):
    parts = callback_query.data.split(":")
    token = parts[1]
    home = len(parts) > 2 and parts[2] == "home"
    if token == "noop":
        await callback_query.answer()
        return
    page_idx = int(token)
    if not (0 <= page_idx < NUM_PAGES):
        await callback_query.answer("Out of range.", show_alert=False)
        return
    try:
        await callback_query.edit_message_caption(
            caption=_build_caption(page_idx),
            parse_mode=ParseMode.HTML,
            reply_markup=_build_keyboard(page_idx, home=home),
        )
    except Exception as exc:
        if "MESSAGE_NOT_MODIFIED" in str(exc).upper():
            await callback_query.answer()
            return
        await callback_query.answer(f"Update failed: {exc}", show_alert=True)
        return
    await callback_query.answer()
