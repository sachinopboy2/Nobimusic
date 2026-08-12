"""/stats — sudo-only diagnostic snapshot of the bot.

Shows reach (registered chats split by type), live playback state, sudo
list size, and library versions. Useful as a first quick check when
something feels off.
"""

import logging
import os
import time

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from bot.config import BOT_NAME
from bot.utils import chats
from bot.utils import emoji as e
from bot.utils import kvstore
from bot.utils import queue as q
from bot.utils import sudo as sudo_store
from bot.utils.owner import get_owner_ids, is_sudo

logger = logging.getLogger("WarbornMusic.stats")

# Stamp the process start time so /stats can show uptime. Set at import.
_START_TS = time.time()


def _humanize_seconds(s: float) -> str:
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    if s < 86400:
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h {m}m"
    d = s // 86400
    h = (s % 86400) // 3600
    return f"{d}d {h}h"


def _versions() -> dict:
    out = {"yt_dlp": "?", "pyrofork": "?", "py_tgcalls": "?", "python": "?"}
    try:
        import sys
        out["python"] = sys.version.split()[0]
    except Exception:
        pass
    try:
        import yt_dlp
        out["yt_dlp"] = yt_dlp.version.__version__
    except Exception:
        pass
    try:
        import pyrogram
        out["pyrofork"] = pyrogram.__version__
    except Exception:
        pass
    try:
        import pytgcalls
        out["py_tgcalls"] = pytgcalls.__version__
    except Exception:
        pass
    return out


@Client.on_message(filters.command("stats"))
async def stats_command(client, message):
    if not message.from_user:
        return
    if not await is_sudo(message.from_user.id):
        owners = await get_owner_ids()
        await message.reply_text(
            f"🔒 {e.SHIELD} <b>Sudo only</b>\n\n"
            f"<b>Your ID:</b> <code>{message.from_user.id}</code>\n"
            f"<b>Owner(s):</b> <code>{', '.join(str(i) for i in sorted(owners)) or '(none)'}</code>\n\n"
            "<i>Owner can grant access with /addsudo, or set OWNER_ID/SUDO_USERS in .env.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    all_chats = chats.all_chats()
    # Chat ID conventions:
    #   user_id > 0           → private DM
    #   -100...               → supergroup or channel
    #   negative without -100 → legacy basic group
    dms = sum(1 for c in all_chats if c > 0)
    supergroups = sum(1 for c in all_chats if c < 0 and str(c).startswith("-100"))
    legacy_groups = sum(1 for c in all_chats if c < 0 and not str(c).startswith("-100"))

    # Live playback — iterate chats and ask the queue module.
    active_chats = 0
    queued_total = 0
    for c in all_chats:
        if q.is_active(c):
            active_chats += 1
        queued_total += len(q.upcoming(c))

    sudoers = sudo_store.all_sudoers()

    v = _versions()
    uptime = _humanize_seconds(time.time() - _START_TS)

    cookies_path = os.getenv("COOKIES_FILE", "")
    cookies_status = "✅ set" if cookies_path and os.path.exists(cookies_path) else "❌ missing"

    # Persistence mode — the usual reason reach/DM counts reset on redeploy is
    # Redis being off, so surface it right here where a regression is noticed.
    storage_status = (
        "✅ Redis (survives redeploys)" if kvstore.enabled()
        else "⚠️ local JSON — EPHEMERAL, resets on redeploy (set REDIS_URL)"
    )

    text = (
        f"{e.GEAR} <b>{BOT_NAME} — Stats</b>\n\n"
        f"{e.PEOPLE} <b>Reach</b>\n"
        f"• Total chats: <b>{len(all_chats)}</b>\n"
        f"• Supergroups / channels: {supergroups}\n"
        f"• Legacy groups: {legacy_groups}\n"
        f"• DMs (users who started bot): {dms}\n\n"
        f"{e.MUSIC} <b>Playback</b>\n"
        f"• Streaming in: {active_chats} chat(s)\n"
        f"• Tracks queued (all chats): {queued_total}\n\n"
        f"{e.CROWN} <b>Admin</b>\n"
        f"• Sudoers: {len(sudoers)} (plus owner)\n\n"
        f"{e.BOLT} <b>Runtime</b>\n"
        f"• Uptime: {uptime}\n"
        f"• Python: {v['python']}\n"
        f"• pyrofork: {v['pyrofork']}\n"
        f"• py-tgcalls: {v['py_tgcalls']}\n"
        f"• yt-dlp: {v['yt_dlp']}\n"
        f"• Cookies: {cookies_status}\n"
        f"• Storage: {storage_status}\n"
    )

    await message.reply_text(text, parse_mode=ParseMode.HTML)
