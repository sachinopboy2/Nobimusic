"""/aura — random aura check.

Three independent rolls per call: n (0-100), caption template, GIF —
no correlation between them. Reuses the resolver + GIF-delivery chain
from `bot.utils.social_commands` (URL-direct → userbot
download+upload → bot download+upload → caller handles caption-only
fallback).

Plugin-to-plugin imports are banned in this repo (pyrofork's
plugins-root scanner gets confused by nested re-entrant imports of
other plugin modules during handler registration). Anything shared
with /pat goes through `bot.utils.social_commands` instead.
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

logger = logging.getLogger("WarbornMusic.aura")


_AURA_CAPTIONS = [
    '<emoji id="6116352966480895996">📡</emoji> {target} has been scanned... aura level: {n}%',
    '<emoji id="6178978331300467171">✨</emoji> Aura check complete — {target} is sitting at {n}%',
    '<emoji id="5271810272640643747">🔮</emoji> The universe has spoken: {target}\'s aura is {n}%',
    '<emoji id="6170427231802757303">⚡</emoji> {target}\'s aura reading just came in at {n}%',
    '<emoji id="6233510010639355761">🌌</emoji> Cosmic aura levels for {target}: {n}%',
    '<emoji id="5409242916805696077">🧿</emoji> {target} radiates exactly {n}% aura right now',
    '<emoji id="5978835896143714365">💫</emoji> Aura sensors confirm {target} is at {n}%',
    '<emoji id="6115889410660638621">🎴</emoji> Fate has assigned {target} an aura of {n}%',
    '<emoji id="5427206638996037048">🌀</emoji> {target}\'s current aura output: {n}%',
    '<emoji id="5269617691836058799">🪄</emoji> Mystic reading: {target} carries {n}% aura today',
]

# Local assets committed under bot/assets/aura/. Previously these were
# tmpfiles.org share links, but tmpfiles is a temp host (~1h TTL) — the
# GIFs kept 404ing once they expired, and every /aura fell through to
# caption-only. Storing them in the repo makes them permanent and
# removes the external-fetch dependency entirely. `send_media_gif`
# detects local paths and routes via the userbot+bot upload fallback.
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "aura"
_AURA_GIFS = [
    str(_ASSETS_DIR / "01_sungjinwoo.mp4"),
    str(_ASSETS_DIR / "02_piccolo.mp4"),
    str(_ASSETS_DIR / "03_sanji.mp4"),
    str(_ASSETS_DIR / "04_jjk.mp4"),
    str(_ASSETS_DIR / "05_zoro.mp4"),
    str(_ASSETS_DIR / "06_flins.mp4"),
]


def _render(template: str, target_mention: str, n: int) -> str:
    """Local — aura templates use {target}+{n}, intentionally separate
    from social_commands since pat's slots ({user1}/{user2}/{eN}) differ.
    """
    return template.format(target=target_mention, n=n)


def _strip_emoji_tags(template: str) -> str:
    """Last-resort plain-text fallback: replace <emoji id="X">Y</emoji>
    with Y (or _FALLBACK if empty) so the line still reads if HTML
    parsing fails.
    """
    import re
    return re.sub(
        r'<emoji id="\d+">([^<]*)</emoji>',
        lambda m: m.group(1) or _FALLBACK,
        template,
    )


@Client.on_message(filters.command("aura"))
async def aura_command(client, message):
    # Trip-wire: if this line doesn't appear in logs when /aura is sent,
    # the handler isn't being bound at all (pyrofork scan issue, not a
    # bug in the body below).
    logger.info(
        "aura_command fired in chat=%s by user=%s reply=%s",
        message.chat.id if message.chat else None,
        message.from_user.id if message.from_user else None,
        bool(message.reply_to_message),
    )

    try:
        _target, target_mention = await resolve_target(client, message)
    except Exception:
        logger.exception("aura: resolve_target raised")
        target_mention = None

    # No reply / no resolvable target → check the sender's own aura.
    if target_mention is None:
        target_mention = attacker_mention(message)

    # Three fully independent rolls — no correlation between them.
    n = random.randint(0, 100)
    template = random.choice(_AURA_CAPTIONS)
    gif_url = random.choice(_AURA_GIFS)

    caption = _render(template, target_mention, n)

    # Full delivery chain: URL-direct → userbot upload → bot upload.
    try:
        ok = await send_media_gif(client, message.chat.id, gif_url, caption, message.id)
    except Exception:
        logger.exception("aura: send_media_gif raised")
        ok = False
    if ok:
        return
    logger.info("aura: gif send failed across all paths — sending caption only")

    # Caption-only fallback (HTML first).
    try:
        await message.reply_text(
            caption, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
        )
        return
    except Exception:
        logger.exception("aura: HTML caption reply failed, retrying plain")

    # Last resort: strip <emoji> tags, send plain text.
    try:
        await message.reply_text(
            _render(_strip_emoji_tags(template), target_mention, n),
            disable_web_page_preview=True,
        )
    except Exception:
        logger.exception("aura: plain caption reply failed too")
