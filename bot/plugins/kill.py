"""/kill — fun 50/50 roleplay command.

Triggers:
  /kill                  — reply-mode: target is the replied-to user
  /kill @username
  /kill <user_id>
  /kill <text_mention>   — Telegram text-mention entity

Each invocation rolls a 50/50:
  success → "💀 {attacker} killed {target}. Case closed. ..."   + success.mp4
  failure → "{attacker} attempted to kill {target}. Better luck …" + fail.mp4

GIFs are downloaded once and cached in /tmp so we don't re-fetch them
each call. If the GIF can't be downloaded the bot still sends the
text-only message (graceful degradation).

The two custom-emoji ids are baked into the messages via pyrofork's
<emoji id="..."> HTML tag; non-premium clients render the fallback
glyph between the tags (💀 / ⚔️).
"""

import asyncio
import logging
import os
import random
import tempfile
from typing import Optional

import aiohttp
from pyrogram import Client, filters
from pyrogram.enums import MessageEntityType, ParseMode

logger = logging.getLogger("WarbornMusic.kill")

# Operator-supplied media for the /kill outcome. Defaults are public
# placeholders; override with KILL_SUCCESS_MEDIA / KILL_FAILURE_MEDIA in .env.
#   Success → animated MP4 (sent as send_animation)
#   Failure → still JPG     (sent as send_photo)
_SUCCESS_MEDIA_URL = os.getenv(
    "KILL_SUCCESS_MEDIA", "https://tmpfiles.org/wlws0Kf74MoM/kirby-meme.mp4"
).strip()
_SUCCESS_KIND = "animation"
_FAILURE_MEDIA_URL = os.getenv(
    "KILL_FAILURE_MEDIA", "https://i.ibb.co/fz8rSyTf/7aa07c2ea06d.jpg"
).strip()
_FAILURE_KIND = "photo"

# Premium custom-emoji ids from the spec.
_EMOJI_FAIL = "6181421239978956035"
_EMOJI_KILL = "5352585602317426381"

_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)

# Cache: source URL -> local path on disk.
_gif_cache: dict[str, str] = {}
_cache_lock = asyncio.Lock()


def _candidate_urls(url: str) -> list[str]:
    """tmpfiles.org's share URL renders an HTML preview page; the actual
    media is at /dl/<id>/<name>. Try the share URL first, then fall back
    to the /dl/ form for tmpfiles links specifically.
    """
    if not url:
        return []
    out = [url]
    if "tmpfiles.org/" in url and "/dl/" not in url:
        out.append(url.replace("tmpfiles.org/", "tmpfiles.org/dl/", 1))
    return out


def _suffix_for(url: str) -> str:
    """Best-effort suffix from the URL path. Used only for the temp
    filename — the actual send method (animation vs photo) is decided
    by _SUCCESS_KIND / _FAILURE_KIND.
    """
    tail = url.rsplit("/", 1)[-1].lower()
    for ext in (".mp4", ".gif", ".webm", ".jpg", ".jpeg", ".png", ".webp"):
        if tail.endswith(ext):
            return ext
    return ".bin"


async def _ensure_media(url: str) -> Optional[str]:
    """Resolve a remote media URL to a local path. Returns None on failure."""
    if not url:
        return None

    async with _cache_lock:
        cached = _gif_cache.get(url)
        if cached and os.path.exists(cached):
            return cached

        for try_url in _candidate_urls(url):
            try:
                async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT) as s:
                    async with s.get(try_url, allow_redirects=True) as resp:
                        if resp.status != 200:
                            continue
                        ctype = (resp.headers.get("Content-Type") or "").lower()
                        if "text/html" in ctype:
                            continue
                        data = await resp.read()
                        if not data or len(data) < 512:
                            continue
                fd, path = tempfile.mkstemp(
                    suffix=_suffix_for(url), prefix="kill_media_"
                )
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                _gif_cache[url] = path
                return path
            except Exception as exc:
                logger.info("kill media fetch %s failed: %s", try_url, exc)
                continue

        logger.warning("kill: could not fetch any candidate of %r", url)
        return None


async def _resolve_target(client, message):
    """Return (user, mention_html) for the /kill target, or (None, None)."""
    for ent in (message.entities or []):
        if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
            return ent.user, ent.user.mention

    reply = message.reply_to_message
    if reply and reply.from_user:
        return reply.from_user, reply.from_user.mention

    if len(message.command) < 2:
        return None, None

    raw = message.command[1].lstrip("@")
    from bot.client import userbot
    try:
        if raw.isdigit():
            u = await client.get_users(int(raw))
        else:
            try:
                u = await userbot.get_users(raw)
            except Exception:
                u = await client.get_users(raw)
        return u, u.mention
    except Exception:
        if raw.isdigit():
            uid = int(raw)
            return None, f'<a href="tg://user?id={uid}">user {uid}</a>'
        return None, None


def _attacker_mention(message) -> str:
    user = message.from_user
    if not user:
        return "someone"
    return user.mention or (user.first_name or str(user.id))


@Client.on_message(filters.command(["kill", "murder"]))
async def kill_command(client, message):
    logger.info(
        "kill_command fired in chat=%s by user=%s reply=%s args=%s",
        message.chat.id if message.chat else None,
        message.from_user.id if message.from_user else None,
        bool(message.reply_to_message),
        message.command[1:] if message.command else [],
    )
    try:
        target, target_mention = await _resolve_target(client, message)
    except Exception:
        logger.exception("kill: _resolve_target raised")
        await message.reply_text("🗡 Couldn't resolve the target — try a different form.")
        return
    logger.info("kill: target=%s mention=%r", target.id if target else None, target_mention)
    if target_mention is None:
        await message.reply_text(
            "🗡 Usage:\n"
            "• Reply to a user's message with `/kill`\n"
            "• `/kill <user_id>`\n"
            "• `/kill @username`"
        )
        return

    attacker_mention = _attacker_mention(message)

    # Optional self-protection: the bot itself can never die.
    target_is_self = bool(target and target.is_self)
    if target_is_self:
        await message.reply_text(
            f'<emoji id="{_EMOJI_FAIL}">⚔️</emoji> '
            f"{attacker_mention} attempted to kill the bot. "
            f"The attempt failed. The Shogun is eternal. ⚡",
            parse_mode=ParseMode.HTML,
        )
        return

    # 50/50.
    success = random.random() < 0.5
    logger.info("kill: roll=%s", "SUCCESS" if success else "FAILURE")

    if success:
        text = (
            f'<emoji id="{_EMOJI_KILL}">💀</emoji> '
            f"{attacker_mention} killed {target_mention}.\n"
            f"Case closed. No second chances."
        )
        media_path = await _ensure_media(_SUCCESS_MEDIA_URL)
        media_kind = _SUCCESS_KIND
    else:
        text = (
            f'<emoji id="{_EMOJI_FAIL}">⚔️</emoji> '
            f"{attacker_mention} attempted to kill {target_mention}.\n"
            f"The attempt failed. Better luck in another timeline."
        )
        media_path = await _ensure_media(_FAILURE_MEDIA_URL)
        media_kind = _FAILURE_KIND

    # Prefer URL-based send: Telegram fetches the media server-side so we
    # don't have to upload chunks via the bot's media DC (that path hangs
    # for the bot client in this pyrofork+ntgcalls build — confirmed by
    # log gaps with no completion or exception). If the URL send fails or
    # times out, fall back to the local-file upload, then to text-only.
    success_url, success_kind = _SUCCESS_MEDIA_URL, _SUCCESS_KIND
    failure_url, failure_kind = _FAILURE_MEDIA_URL, _FAILURE_KIND
    chosen_url = success_url if success else failure_url
    # tmpfiles.org needs /dl/ for direct media; ibb.co URLs are already direct.
    chosen_url = _candidate_urls(chosen_url)[-1]

    sent = False
    for attempt in ("url", "file"):
        if sent:
            break
        try:
            payload = chosen_url if attempt == "url" else media_path
            if not payload:
                continue
            logger.info("kill: send attempt=%s via %s", attempt, media_kind)
            if media_kind == "animation":
                coro = client.send_animation(
                    chat_id=message.chat.id,
                    animation=payload,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=message.id,
                )
            else:
                coro = client.send_photo(
                    chat_id=message.chat.id,
                    photo=payload,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    reply_to_message_id=message.id,
                )
            # Hard timeout: pyrofork's media-DC upload path has hung
            # indefinitely on this bot in earlier runs, swallowing the
            # caller. wait_for converts the hang into TimeoutError so we
            # can fall through to the next attempt instead of leaking
            # the handler task.
            await asyncio.wait_for(coro, timeout=25)
            sent = True
            logger.info("kill: media sent OK via %s", attempt)
        except asyncio.TimeoutError:
            logger.warning("kill: send via %s timed out after 25s", attempt)
        except Exception:
            logger.exception("kill: send via %s failed", attempt)

    if sent:
        return

    try:
        await message.reply_text(text, parse_mode=ParseMode.HTML)
        logger.info("kill: text-fallback sent OK")
    except Exception:
        logger.exception("kill: text-fallback also failed")
