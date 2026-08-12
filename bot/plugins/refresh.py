"""/refresh — owner/sudo cache & runtime refresh WITHOUT touching playback.

Clears orphaned playback/download caches (never a file backing a live
stream), the yt-dlp metadata cache, and stale cookie tempfiles, then runs a
GC pass. Does NOT leave voice chats, stop playback, clear queues, interrupt
downloads, or restart — it only reclaims what nothing is using.
"""

import gc
import logging
import os

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from bot.utils import cookie_manager
from bot.utils import emoji as e
from bot.utils import play_actions, playback
from bot.utils.owner import get_owner_ids, is_sudo

logger = logging.getLogger("WarbornMusic.refresh")


def _rss_kb() -> int:
    """Resident set size in KiB from /proc, or 0 if unavailable."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0


def _human_bytes(n: int) -> str:
    v = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} GB"


def _clear_ytdlp_cache() -> None:
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({"quiet": True, "no_warnings": True}) as ydl:
            ydl.cache.remove()
    except Exception as exc:
        logger.info("refresh: yt-dlp cache clear skipped (%s)", exc)


def _clear_cookie_tempfiles() -> int:
    """Remove leftover per-request cookie tempfile copies (never the masters
    or the active jar)."""
    from bot.utils import player
    active = player.active_youtube_cookies()
    removed = 0
    for p in list(player._COOKIE_TEMPFILES):
        if p == active:
            continue
        try:
            if os.path.exists(p):
                os.remove(p)
            player._COOKIE_TEMPFILES.remove(p)
            removed += 1
        except (OSError, ValueError):
            pass
    return removed


@Client.on_message(filters.command("refresh"))
async def refresh_command(client, message):
    if not message.from_user:
        return
    if not await is_sudo(message.from_user.id):
        owners = await get_owner_ids()
        await message.reply_text(
            f"🔒 {e.SHIELD} <b>Sudo only</b>\n"
            f"<b>Your ID:</b> <code>{message.from_user.id}</code>\n"
            f"<b>Owner(s):</b> <code>{', '.join(str(i) for i in sorted(owners)) or '(none)'}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    rss_before = _rss_kb()

    play_removed, play_freed = playback.purge_orphan_media()
    dl_removed, dl_freed = play_actions.purge_downloads()
    ck_removed = _clear_cookie_tempfiles()
    _clear_ytdlp_cache()
    collected = gc.collect()

    rss_after = _rss_kb()
    reclaimed_kb = max(0, rss_before - rss_after)
    files = play_removed + dl_removed + ck_removed
    disk_freed = play_freed + dl_freed
    cj = cookie_manager.stats()

    mem_line = (
        f"• Memory reclaimed: <b>{_human_bytes(reclaimed_kb * 1024)}</b>\n"
        if reclaimed_kb else ""
    )
    await message.reply_text(
        f"{e.BOLT} <b>Runtime refreshed</b>\n\n"
        f"{e.BROOM if hasattr(e, 'BROOM') else '🧹'} <b>Caches cleared successfully</b>\n"
        f"• Temp files removed: <b>{files}</b>\n"
        f"• Disk freed: <b>{_human_bytes(disk_freed)}</b>\n"
        f"• GC objects collected: <b>{collected}</b>\n"
        f"{mem_line}"
        f"• Cookie jars: <b>{cj['healthy']}/{cj['jars']}</b> healthy\n\n"
        "<i>Active voice chats, playback and queues were left untouched.</i>",
        parse_mode=ParseMode.HTML,
    )
    logger.info(
        "refresh by %s: files=%d disk=%dB gc=%d rss_reclaimed=%dKB",
        message.from_user.id, files, disk_freed, collected, reclaimed_kb,
    )
