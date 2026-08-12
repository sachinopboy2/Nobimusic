"""/pat — soft, wholesome headpat command.

Triggers:
  /pat                — reply-mode: target is the replied-to user
  /pat @username
  /pat <user_id>
  /pat <text_mention> — Telegram text-mention entity

Each call makes TWO independent random rolls:
  - one caption template from `_CAPTIONS` (emoji ids + template stay
    bonded because the template's {e0}/{e1}/... slots reference that
    specific emoji list)
  - one GIF path from `_GIFS`
No correlation between the two — every (caption, gif) combination is
possible. Both are sent as a single animation message: GIF as the
animation, rendered caption merged on top.

GIFs live as committed assets under bot/assets/pat/ — local files,
no tmpfiles/external-host dependency. `send_media_gif` recognizes
local paths and routes them through the userbot+bot upload fallback.

Helpers (target resolution + GIF delivery chain) live in
`bot.utils.social_commands` so /aura and any future similar command
can reuse them without one plugin importing another. Plugin-to-plugin
imports are banned in this repo.
"""

import logging
import random
from pathlib import Path

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from bot.utils.social_commands import (
    _FALLBACK,
    attacker_mention,
    resolve_target,
    send_media_gif,
)

logger = logging.getLogger("WarbornMusic.pat")


# Caption pool. Each entry: (emoji_ids, template). emoji_ids stays
# bonded to its template (the template's {e0}/{e1}/{eN} slots
# reference indexes into this list). Templates also have {user1}
# (sender mention) and {user2} (target mention) slots.
_CAPTIONS: list[tuple[list[str], str]] = [
    (
        ["5386414139130260061", "4956436416142771580"],
        "{e0} {e1} {user1} gently headpats {user2}.\n\n"
        "A tiny moment of peace in the middle of the chaos.",
    ),
    (
        ["5830278651026873081"],
        "{e0} {user1} gives {user2} a soft headpat.\n\n"
        "+10 Comfort\n"
        "+100 Serotonin.",
    ),
    (
        ["5911493248483859403"],
        "{e0} {user1} reaches over and headpats {user2}.\n\n"
        "Mission accomplished: Emotional support delivered.",
    ),
    (
        ["5222179653497670288"],
        "{e0} {user1} headpats {user2}.\n\n"
        "A rare gesture. Handle with care.",
    ),
    (
        ["5215226264654213464"],
        "{e0} {user1} gently pats {user2}'s head.\n\n"
        "Achievement Unlocked:\n"
        "Certified Comfort Provider.",
    ),
    (
        ["5818719339255176305", "5962830584551052132", "4958577444454925201"],
        "{e0} {e1} {user1} gently headpats {user2}.\n\n"
        "\"You're doing better than you think.\" {e2}",
    ),
    (
        ["5366472202248009747", "5386414139130260061",
         "5341695605364244563", "6181428412574339821"],
        "{e0} {e1} {user1} softly pats {user2}'s head.\n\n"
        "For just a moment, the world feels a little lighter. {e2} {e3}",
    ),
    (
        ["5445278980909310899", "5235513242029139973",
         "5440716467215540650", "5460724202996773009"],
        "{e0} {e1} {user1} gives {user2} a warm headpat.\n\n"
        "+1 Happy Thought {e2}\n"
        "+1 Safe Feeling {e3}",
    ),
    (
        ["5769543759012303026", "5460858729962421671",
         "5215226264654213464", "4956468890390496140"],
        "{e0} {e1} {user1} carefully headpats {user2}.\n\n"
        "No words needed. Just a quiet reminder that someone cares. {e2} {e3}",
    ),
    (
        ["4956708038464504901", "5818976758120067408",
         "5969733271305588971", "4958577444454925201"],
        "{e0} {e1} {user1} gives {user2} the gentlest headpat imaginable.\n\n"
        "May your worries shrink, your smile grow, and your day become a "
        "little brighter. {e2} {e3}",
    ),
]


# GIF pool — local assets committed under bot/assets/pat/. Previously
# tmpfiles.org URLs that 404'd within an hour, taking every /pat down
# to caption-only. Storing them in the repo makes them permanent and
# removes the external-fetch dependency. `send_media_gif` detects
# local paths and routes via the userbot+bot upload fallback.
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "pat"
_GIFS = [
    str(_ASSETS_DIR / "01_gawrgura.mp4"),
    str(_ASSETS_DIR / "02_kobayashi.mp4"),
    str(_ASSETS_DIR / "03_sakuta.mp4"),
    str(_ASSETS_DIR / "04_vtuber.mp4"),
    str(_ASSETS_DIR / "05_anya.mp4"),
    str(_ASSETS_DIR / "06_senpai.mp4"),
    str(_ASSETS_DIR / "07_fern.mp4"),
    str(_ASSETS_DIR / "08_neko.mp4"),
]


def _render(template: str, emoji_ids: list[str], user1_mention: str, user2_mention: str) -> str:
    tags = {
        f"e{i}": f'<emoji id="{eid}">{_FALLBACK}</emoji>'
        for i, eid in enumerate(emoji_ids)
    }
    return template.format(user1=user1_mention, user2=user2_mention, **tags)


@Client.on_message(filters.command(["pat", "headpat"]))
async def pat_command(client, message):
    logger.info(
        "pat_command fired in chat=%s by user=%s reply=%s args=%s",
        message.chat.id if message.chat else None,
        message.from_user.id if message.from_user else None,
        bool(message.reply_to_message),
        message.command[1:] if message.command else [],
    )

    try:
        target, target_mention = await resolve_target(client, message)
    except Exception:
        logger.exception("pat: resolve_target raised")
        await message.reply_text("🤚 Couldn't resolve the target — try a different form.")
        return

    if target_mention is None:
        await message.reply_text(
            "🤚 Usage:\n"
            "• Reply to a user's message with `/pat`\n"
            "• `/pat <user_id>`\n"
            "• `/pat @username`"
        )
        return

    sender_mention = attacker_mention(message)

    # Self-pat: still allowed but with a dedicated string so it doesn't look broken.
    if target and message.from_user and target.id == message.from_user.id:
        await message.reply_text(
            f'<emoji id="5215226264654213464">{_FALLBACK}</emoji> '
            f"{sender_mention} pats their own head.\n\n"
            f"Self-care counts.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Two fully independent rolls — no correlation between caption and GIF.
    emoji_ids, template = random.choice(_CAPTIONS)
    gif_path = random.choice(_GIFS)
    caption = _render(template, emoji_ids, sender_mention, target_mention)

    # `send_media_gif` walks (for local paths) userbot upload → bot upload.
    ok = await send_media_gif(client, message.chat.id, gif_path, caption, message.id)
    if ok:
        logger.info("pat: gif+caption reply ok")
        return
    logger.info("pat: gif send failed across all paths — sending caption only")

    # Text-only fallback: caption alone, no URL paste.
    try:
        await message.reply_text(
            caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
        )
    except Exception:
        logger.exception("pat: HTML caption reply failed, retrying plain")
        plain = template.format(
            user1=sender_mention, user2=target_mention,
            **{f"e{i}": _FALLBACK for i in range(len(emoji_ids))},
        )
        try:
            await message.reply_text(plain, disable_web_page_preview=True)
        except Exception:
            logger.exception("pat: plain caption reply failed too")
