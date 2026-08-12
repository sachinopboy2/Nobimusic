"""/update — Git pull latest code and restart.
/restart — Restart the bot immediately.

Owner-only commands. Works even after long uptime.
"""

import os
import sys
import subprocess
import html as _html

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from bot.config import OWNER_ID
from bot.utils import emoji as e

_HTML = ParseMode.HTML


def _is_owner(user_id: int) -> bool:
    """True if user_id matches any OWNER_ID (single int or comma-separated list)."""
    raw = str(OWNER_ID)
    owners = {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}
    return user_id in owners


# ── /restart ───────────────────────────────────────
@Client.on_message(filters.command("restart"))
async def restart_command(client, message):
    if not _is_owner(message.from_user.id):
        await message.reply_text(
            f"{e.BLOCK} <b>Owner only</b>\n"
            "<i>This command is restricted to the bot owner.</i>",
            parse_mode=_HTML,
        )
        return

    await message.reply_text(
        f"{e.COMET} <b>Restarting...</b>\n"
        f"<i>Bot will be back in a few seconds.</i>",
        parse_mode=_HTML,
    )
    await client.stop()
    os.execv(sys.executable, [sys.executable] + sys.argv)


# ── /update ────────────────────────────────────────
@Client.on_message(filters.command("update"))
async def update_command(client, message):
    if not _is_owner(message.from_user.id):
        await message.reply_text(
            f"{e.BLOCK} <b>Owner only</b>\n"
            "<i>This command is restricted to the bot owner.</i>",
            parse_mode=_HTML,
        )
        return

    msg = await message.reply_text(
        f"{e.SEARCH} <b>Checking for updates...</b>",
        parse_mode=_HTML,
    )

    # 1. Fetch
    try:
        fetch = subprocess.run(
            ["git", "fetch", "origin"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:
        await msg.edit_text(
            f"{e.WARNING} <b>Fetch failed</b>\n"
            f"<code>{_html.escape(str(exc)[:400])}</code>",
            parse_mode=_HTML,
        )
        return

    if fetch.returncode != 0:
        await msg.edit_text(
            f"{e.WARNING} <b>Fetch failed</b>\n"
            f"<code>{_html.escape(fetch.stderr[:400])}</code>",
            parse_mode=_HTML,
        )
        return

    # 2. How many commits behind?
    try:
        behind = subprocess.run(
            ["git", "rev-list", "HEAD..origin/main", "--count"],
            capture_output=True, text=True, timeout=15,
        )
        commits_behind = int(behind.stdout.strip() or "0")
    except Exception:
        commits_behind = 0

    if commits_behind == 0:
        await msg.edit_text(
            f"{e.CHECK} <b>Already up-to-date!</b>\n"
            "<i>No new changes on remote.</i>",
            parse_mode=_HTML,
        )
        return

    # 3. Pull
    try:
        pull = subprocess.run(
            ["git", "pull", "origin", "main"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:
        await msg.edit_text(
            f"{e.WARNING} <b>Pull failed</b>\n"
            f"<code>{_html.escape(str(exc)[:400])}</code>",
            parse_mode=_HTML,
        )
        return

    if pull.returncode != 0:
        await msg.edit_text(
            f"{e.WARNING} <b>Pull failed</b>\n"
            f"<code>{_html.escape(pull.stderr[:400])}</code>",
            parse_mode=_HTML,
        )
        return

    # 4. Success → Restart
    await msg.edit_text(
        f"{e.CHECK} <b>Updated!</b>\n"
        f"{e.INBOX} Pulled {commits_behind} commit(s).\n\n"
        f"{e.COMET} <b>Restarting...</b>",
        parse_mode=_HTML,
    )
    await client.stop()
    os.execv(sys.executable, [sys.executable] + sys.argv)
