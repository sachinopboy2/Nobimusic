import asyncio
import html
import os
import time

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from bot.utils import emoji as e
from bot.utils.downloader import (
    check_size_and_duration,
    download_video,
)
from bot.utils.logchannel import log_download
from bot.utils.player import YouTubeAuthRequiredError, _try_extract
from bot.utils.resolver import resolve_url

_HTML = ParseMode.HTML


@Client.on_message(filters.command("video"))
async def video_command(client, message):
    if len(message.command) < 2:
        await message.reply_text(
            "🎬 <b>Download a video</b>\n"
            "<code>/video &lt;name or YouTube/SoundCloud/Spotify/Resso link&gt;</code>\n"
            "<i>I'll fetch it (≤720p mp4) and send it here.</i>", parse_mode=_HTML)
        return

    query = " ".join(message.command[1:])
    status = await message.reply_text(
        f"{e.SPARKLE} <b>Searching…</b>", parse_mode=_HTML)

    url, label = await resolve_url(query)
    if not url:
        await status.edit_text(f"❌ {html.escape(str(label))}", parse_mode=_HTML)
        return

    await status.edit_text(
        f"{e.SPARKLE} <b>Checking…</b>\n<i>{html.escape(str(label))}</i>", parse_mode=_HTML)
    try:
        probe = await asyncio.to_thread(_try_extract, url)
    except YouTubeAuthRequiredError:
        await status.edit_text(YouTubeAuthRequiredError.USER_MESSAGE)
        await log_download(client, user=message.from_user, url=url,
                           media_type="video", ok=False,
                           error="YouTube bot-wall (cookies required)")
        return
    title = (probe.get("title") if isinstance(probe, dict) else None) or label
    too_big = check_size_and_duration(probe or {})
    if too_big:
        await status.edit_text(f"❌ {html.escape(str(too_big))}", parse_mode=_HTML)
        return

    await status.edit_text(
        f"{e.BOLT} <b>Downloading…</b>\n<i>{html.escape(str(title))}</i>", parse_mode=_HTML)
    t0 = time.monotonic()
    try:
        path, info = await asyncio.to_thread(download_video, url)
    except Exception as exc:
        await status.edit_text(
            "❌ <b>Download failed</b>\n"
            f"<code>{html.escape(f'{type(exc).__name__}: {exc}')}</code>", parse_mode=_HTML)
        await log_download(client, user=message.from_user, url=url,
                           media_type="video", ok=False, started=t0,
                           error=f"{type(exc).__name__}: {exc}")
        return

    duration = int(info.get("duration") or 0)
    width = int(info.get("width") or 0)
    height = int(info.get("height") or 0)

    try:
        await status.edit_text(
            f"📤 <b>Uploading…</b>\n<i>{html.escape(str(title))}</i>", parse_mode=_HTML)
        await client.send_video(
            chat_id=message.chat.id,
            video=path,
            caption=f"🎬 <b>{html.escape(str(title))}</b>",
            parse_mode=_HTML,
            duration=duration,
            width=width,
            height=height,
            supports_streaming=True,
            reply_to_message_id=message.id,
        )
        await status.delete()
        await log_download(client, user=message.from_user, url=url,
                           media_type="video", ok=True, started=t0,
                           file_size=os.path.getsize(path) if os.path.exists(path) else None)
    except Exception as exc:
        await status.edit_text(
            "❌ <b>Upload failed</b>\n"
            f"<code>{html.escape(f'{type(exc).__name__}: {exc}')}</code>", parse_mode=_HTML)
        await log_download(client, user=message.from_user, url=url,
                           media_type="video", ok=False, started=t0,
                           error=f"upload: {type(exc).__name__}: {exc}")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
