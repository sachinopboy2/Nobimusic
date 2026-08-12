"""Log-channel subsystem.

/setlog (bot/plugins/setlog.py) persists a single destination chat id
here; the log_* helpers below format and send event logs to it. Every
sender is best-effort — a broken/unset log chat must never affect the
user-facing flow, so nothing in this module raises.

Platform handling is fully dynamic: detect_platform() derives the
platform from the URL, PLATFORM_EMOJIS supplies the matching custom
emoji, and unknown platforms fall back to the plain 📥 while still
showing the detected name. Adding a new platform = one dict entry.
"""

import html
import json
import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from pyrogram.enums import ParseMode

logger = logging.getLogger("WarbornMusic.logchannel")

from bot.utils import kvstore

LOG_CHAT_FILE = os.getenv("LOG_CHAT_FILE", "log_chat.json")
_KV = "logchannel"

_state: dict = {}
_loaded = False


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with open(LOG_CHAT_FILE) as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("chat_id"), int):
            _state["chat_id"] = data["chat_id"]
    except (OSError, ValueError):
        pass
    if kvstore.enabled():
        remote = kvstore.load(_KV)
        if isinstance(remote, dict) and isinstance(remote.get("chat_id"), int):
            _state["chat_id"] = remote["chat_id"]  # Redis authoritative
        elif "chat_id" in _state:
            kvstore.save(_KV, {"chat_id": _state["chat_id"]})  # migrate local up


def get_log_chat() -> int | None:
    """Resolve the active log destination.

    Priority: a chat set at runtime via /setlog (persisted here / in
    Redis) wins; otherwise fall back to the LOG_GROUP_ID configured in
    .env so logging works immediately after deploy with zero setup.
    """
    _load()
    if "chat_id" in _state:
        return _state["chat_id"]
    from bot.config import LOG_GROUP_ID
    return LOG_GROUP_ID


def _persist(payload: dict) -> None:
    tmp = LOG_CHAT_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f)
        os.replace(tmp, LOG_CHAT_FILE)
    except OSError:
        logger.exception("could not persist log chat state")
        try:
            os.remove(tmp)
        except OSError:
            pass
    kvstore.save(_KV, payload)


def set_log_chat(chat_id: int) -> None:
    """Persist chat_id as the (single) log destination. Atomic write,
    same tmp+os.replace pattern as chats.py/greetings.py."""
    _load()
    _state["chat_id"] = chat_id
    _persist({"chat_id": chat_id})


def clear_log_chat() -> bool:
    """Remove the configured log destination. Returns True if one was
    set. Persists the removal."""
    _load()
    had = _state.pop("chat_id", None) is not None
    _persist({})
    return had


# ── Platform detection ───────────────────────────────────────────────

# platform key → custom emoji id. Add a new platform here and every log
# picks it up automatically — nothing else to change.
PLATFORM_EMOJIS: dict[str, int] = {
    "instagram": 5438312655624380182,
    "youtube": 5832211377720137226,
    "pinterest": 5206525339517344010,
    "tiktok": 5436122939562957195,
    "facebook": 5829963585110938467,
    "twitter": 5436304698283958459,
    "reddit": 5303103765136563815,
    "spotify": 6008235948012211945,
}

# Alternate hosts → canonical platform key.
_HOST_ALIASES: dict[str, str] = {
    "youtu.be": "youtube",
    "pin.it": "pinterest",
    "x.com": "twitter",
    "t.co": "twitter",
    "fb.watch": "facebook",
    "fb.com": "facebook",
    "redd.it": "reddit",
    "vm.tiktok.com": "tiktok",
}

# Display-name overrides for platforms whose .title() looks wrong.
_DISPLAY = {"youtube": "YouTube", "tiktok": "TikTok", "soundcloud": "SoundCloud"}

_DEFAULT_EMOJI = "📥"


def detect_platform(url: str) -> str:
    """Platform key for url — a PLATFORM_EMOJIS key when recognised,
    otherwise the URL's second-level domain (so new/unknown platforms
    still get a sensible name)."""
    if "://" not in url:
        url = "https://" + url
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    for alias, key in _HOST_ALIASES.items():
        if host == alias or host.endswith("." + alias):
            return key
    for key in PLATFORM_EMOJIS:
        if key in host:
            return key
    parts = host.split(".")
    return parts[-2] if len(parts) >= 2 else (host or "unknown")


def platform_display(platform: str) -> str:
    return _DISPLAY.get(platform, platform.title() if platform else "Unknown")


def platform_emoji_html(platform: str) -> str:
    """Custom-emoji HTML for platform, or the plain 📥 fallback when the
    platform has no entry in PLATFORM_EMOJIS."""
    eid = PLATFORM_EMOJIS.get(platform)
    if eid is None:
        return _DEFAULT_EMOJI
    return f'<emoji id="{eid}">{_DEFAULT_EMOJI}</emoji>'


# ── Formatting helpers ───────────────────────────────────────────────

_BAR = "━━━━━━━━━━━━━━━━━━━━━━"


def _e(eid: int, fallback: str) -> str:
    return f'<emoji id="{eid}">{fallback}</emoji>'


def _mention(user) -> str:
    if user is None:
        return "Unknown"
    name = html.escape(
        ((user.first_name or "") + " " + (user.last_name or "")).strip() or "Someone"
    )
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def _human_size(n: int | None) -> str:
    if not n:
        return "N/A"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return "N/A"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def build_download_log(*, user, url: str, media_type: str, ok: bool,
                       file_size: int | None = None,
                       started: float | None = None,
                       error: str | None = None) -> str:
    platform = detect_platform(url)
    dl_time = f"{time.monotonic() - started:.1f}s" if started is not None else "N/A"
    outcome = ("media downloaded successfully."
               if ok else "media download FAILED.")
    status = "SUCCESS" if ok else "FAILED"
    status_fb = "✅" if ok else "❌"
    footer = ("Download completed and delivered."
              if ok else "Download failed — see reason above.")
    reason = (
        f"\n{_e(4958689671950369798, '⚠️')} Reason: {html.escape((error or 'unknown')[:300])}"
        if not ok else ""
    )
    return (
        f"{_BAR}\n"
        f"{_e(5443127283898405358, '📥')} DOWNLOAD REQUEST LOG\n"
        f"{_BAR}\n\n"
        f"{platform_emoji_html(platform)} {platform_display(platform)} {outcome}\n\n"
        f"{_e(5352865784508980799, '👤')} Requested By: {_mention(user)}\n"
        f"{_e(6116094499643989575, '🆔')} User ID: {user.id if user else 'N/A'}\n"
        f"{_e(4958689671950369798, '🔗')} Source: {html.escape(url)}\n"
        f"{_e(6170389818342645293, '🎞')} Media Type: {html.escape(media_type)}\n"
        f"{_e(5463172695132745432, '📦')} File Size: {_human_size(file_size)}\n"
        f"{_e(6300622254778616022, '⏱')} Download Time: {dl_time}\n"
        f"{_e(6170209141953403618, '🕒')} Completed At: {_now()}\n"
        f"{_e(4958845510543737828, status_fb)} Status: {status}"
        f"{reason}\n\n"
        f"{_BAR}\n"
        f"{_e(5911161737138149823, '✔️')} {footer}\n"
        f"{_BAR}"
    )


def build_play_log(*, user, chat_title, chat_id, title, is_video: bool, ok: bool,
                   detail: str = "", event: str = "Play") -> str:
    head_fb = "🎬" if is_video else "🎵"
    status = "SUCCESS" if ok else "FAILED"
    status_fb = "✅" if ok else "❌"
    info = (
        f"\n{_e(4958689671950369798, '⚠️')} Info: {html.escape(str(detail))}"
        if detail else ""
    )
    return (
        f"{_BAR}\n"
        f"{_e(5443127283898405358, head_fb)} {event.upper()} LOG\n"
        f"{_BAR}\n\n"
        f"{_e(4958845510543737828, status_fb)} Status: {status}\n"
        f"{_e(5994721794760642534, head_fb)} Track: {html.escape(str(title))}\n"
        f"{_e(4958689671950369798, '💬')} Chat: {html.escape(str(chat_title))} "
        f"(<code>{chat_id}</code>)\n"
        f"{_e(5352865784508980799, '👤')} By: {_mention(user)}"
        f"{info}\n"
        f"{_e(6170209141953403618, '🕒')} At: {_now()}\n\n"
        f"{_BAR}"
    )


# ── Senders (best-effort, never raise) ───────────────────────────────

async def send_log(client, text: str) -> None:
    chat_id = get_log_chat()
    if chat_id is None:
        return
    try:
        await client.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as exc:
        logger.warning("log send to %s failed: %s: %s",
                       chat_id, type(exc).__name__, exc)


async def log_download(client, *, user, url: str, media_type: str, ok: bool,
                       file_size: int | None = None,
                       started: float | None = None,
                       error: str | None = None) -> None:
    try:
        text = build_download_log(
            user=user, url=url, media_type=media_type, ok=ok,
            file_size=file_size, started=started, error=error,
        )
    except Exception:
        logger.exception("could not build download log")
        return
    await send_log(client, text)


async def log_bot_started(client, user) -> None:
    await send_log(
        client,
        f"{_BAR}\n"
        f"{_e(5443127283898405358, '🚀')} BOT START LOG\n"
        f"{_BAR}\n\n"
        f"{_e(5352865784508980799, '👤')} User: {_mention(user)}\n"
        f"{_e(6116094499643989575, '🆔')} User ID: {user.id if user else 'N/A'}\n"
        f"{_e(6170209141953403618, '🕒')} At: {_now()}",
    )


async def log_play_event(client, *, user, chat_title, chat_id, title,
                         is_video: bool, ok: bool, detail: str = "",
                         event: str = "Play") -> None:
    try:
        text = build_play_log(
            user=user, chat_title=chat_title, chat_id=chat_id, title=title,
            is_video=is_video, ok=ok, detail=detail, event=event,
        )
    except Exception:
        logger.exception("could not build play log")
        return
    await send_log(client, text)


async def log_bot_added(client, chat, by_user) -> None:
    title = html.escape(getattr(chat, "title", None) or str(chat.id))
    await send_log(
        client,
        f"{_BAR}\n"
        f"{_e(5443127283898405358, '➕')} BOT ADDED LOG\n"
        f"{_BAR}\n\n"
        f"{_e(4958689671950369798, '💬')} Chat: {title}\n"
        f"{_e(6116094499643989575, '🆔')} Chat ID: {chat.id}\n"
        f"{_e(5352865784508980799, '👤')} Added By: {_mention(by_user)}\n"
        f"{_e(6170209141953403618, '🕒')} At: {_now()}",
    )
