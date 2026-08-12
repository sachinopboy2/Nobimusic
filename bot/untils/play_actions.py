"""Shared playback action logic for /play, /vplay, /skip, /vskip.

Lives in `bot/utils/` (not `bot/plugins/`) deliberately: pyrofork's
plugins-root scanner walks `bot.plugins.*` for handlers, and one
plugin top-level-importing another plugin module risks the scanner
mis-attributing or skipping the importer's handler during the
nested re-entrant import. Audio and video share the same per-chat
queue, so /play+/vplay and /skip+/vskip share their core logic
through this module instead of plugin-to-plugin imports.
"""

import asyncio
import html
import logging
import os
import re
import time

from pyrogram.enums import ChatType, ParseMode

from bot.utils import emoji as e
from bot.utils import queue as q
from bot.utils.logchannel import log_play_event
from bot.utils.np_ui import (
    nowplaying_keyboard,
    queue_added_keyboard,
    render_for_chat,
    render_queue_added,
)
from bot.utils import thumbnail
from bot.utils.playback import (
    end_session,
    ensure_userbot_in_chat,
    get_started_at,
    play_track,
)
from bot.utils.resolver import resolve

logger = logging.getLogger("WarbornMusic.play_actions")

# Premium custom emojis (IDs verified renderable by this bot elsewhere in
# the code). <emoji id> falls back to the glyph if a client lacks premium.
_E_SEARCH = '<emoji id="5271810272640643747">🔮</emoji>'
_E_DL = '<emoji id="6170427231802757303">⚡</emoji>'
_E_VC = '<emoji id="5886268068035827289">🎧</emoji>'
_E_QUEUE = '<emoji id="5334653529741076580">🎶</emoji>'
_E_HINT = '<emoji id="5269617691836058799">🪄</emoji>'

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

DOWNLOAD_DIR = "/tmp/warborn_downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)


def purge_downloads() -> tuple[int, int]:
    """Delete leftover replied-media downloads that are NOT backing a live
    track. Used by /refresh; never removes a file a current stream plays from,
    so downloads/playback aren't interrupted. Returns (removed, bytes_freed)."""
    keep = q.active_sources()
    removed = freed = 0
    try:
        names = os.listdir(DOWNLOAD_DIR)
    except OSError:
        return 0, 0
    for name in names:
        p = os.path.join(DOWNLOAD_DIR, name)
        if p in keep or not os.path.isfile(p):
            continue
        try:
            sz = os.path.getsize(p)
            os.remove(p)
            removed += 1
            freed += sz
        except OSError:
            pass
    return removed, freed


def _replied_media(message):
    """Return (media, label, is_video) for a replied audio/voice/video msg.

    `is_video` reflects the ACTUAL file type, not the command used — so an
    mp3 replied to with /vplay still streams as audio (a video pipeline on
    an audio-only file can't play), and an mp4 replied to with /play streams
    as video.
    """
    reply = message.reply_to_message
    if not reply:
        return None, None, False
    for attr in ("video", "video_note", "audio", "voice"):
        media = getattr(reply, attr, None)
        if media:
            label = (
                getattr(media, "file_name", None)
                or getattr(media, "title", None)
                or attr
            )
            return media, label, attr in ("video", "video_note")
    document = reply.document
    if document and document.mime_type and (
        document.mime_type.startswith("audio/")
        or document.mime_type.startswith("video/")
    ):
        is_video = document.mime_type.startswith("video/")
        return document, document.file_name or "uploaded file", is_video
    return None, None, False


def _replied_url(message):
    """First URL in the replied message's text or caption, or None."""
    reply = message.reply_to_message
    if not reply:
        return None
    body = reply.text or reply.caption or ""
    if not body:
        return None
    m = _URL_RE.search(str(body))
    return m.group(0) if m else None


def _requester_name(message) -> str:
    user = message.from_user
    if not user:
        return "someone"
    return user.first_name or user.username or str(user.id)


# ── Queue-card helpers (used only to render the 'Added to Queue' message) ──
_YT_ID_RE = re.compile(
    r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|shorts/|embed/|v/))([0-9A-Za-z_-]{11})"
)


async def _artwork_url(query, title):
    """Best-effort highest-quality artwork URL for the resolved track. Uses the
    video id from a YouTube-link query directly; for text searches does one
    lightweight YouTube lookup to find the id. None → template renders without
    artwork (never blocks). thumbnail._fetch downgrades maxres→sd→hq as needed."""
    m = _YT_ID_RE.search(query or "")
    if not m:
        try:
            from bot.utils import player
            res = await player.search_youtube_detailed(title or query, limit=1)
            if res:
                m = _YT_ID_RE.search(res[0][0] or "")
        except Exception:
            logger.debug("artwork lookup failed for %r", title or query, exc_info=True)
    return f"https://i.ytimg.com/vi/{m.group(1)}/maxresdefault.jpg" if m else None


async def _track_artwork(track):
    """Artwork url for a track, cached on track.thumb. Resolves by title on
    first use (one lightweight lookup) so queue/skip/auto-advance refreshes and
    the initial player all share one result. Called only after audio starts."""
    art = getattr(track, "thumb", None)
    if art:
        return art
    art = await _artwork_url(None, getattr(track, "title", None))
    try:
        track.thumb = art
    except Exception:
        pass
    return art


def _split_artist(title: str):
    """Best-effort (artist, song) from a 'Artist - Song' title. Falls back to
    (None, title) so the card degrades gracefully."""
    if title and " - " in title:
        artist, song = title.split(" - ", 1)
        artist, song = artist.strip(), song.strip()
        if artist and song:
            return artist, song
    return None, title


def _fmt_eta(seconds: float) -> str:
    if seconds <= 1:
        return "now"
    mins = round(seconds / 60)
    if mins < 1:
        return "under a min"
    return f"~{mins} min"


def _queue_eta(chat_id: int, position: int) -> float:
    """Seconds until a track at 1-indexed queue `position` starts: remaining
    time of the current track + full duration of tracks ahead of it."""
    total = 0.0
    cur = q.now_playing(chat_id)
    if cur and cur.duration:
        started = get_started_at(chat_id)
        elapsed = (time.monotonic() - started) if started else 0
        total += max(0, cur.duration - elapsed)
    for t in q.upcoming(chat_id)[: max(0, position - 1)]:
        total += t.duration or 0
    return total


async def do_play(client, message, *, is_video: bool):
    label_cmd = "/vplay" if is_video else "/play"
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            "👥 <b>Groups only</b>\n"
            f"<i>{label_cmd} works inside a group that has an active voice chat.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    replied_media, replied_label, replied_is_video = _replied_media(message)
    # Reply-to-link: only used when no command args and no replied media,
    # so explicit args still win.
    replied_url = (
        _replied_url(message)
        if (len(message.command) < 2 and not replied_media)
        else None
    )

    if len(message.command) < 2 and not replied_media and not replied_url:
        await message.reply_text(
            f"{_E_HINT} <b>What should I play?</b>\n"
            f"<code>{label_cmd} song name or link</code> — or reply to an audio/video file.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Kick the VC-membership join off NOW, concurrently with resolving/
    # downloading the track — the join doesn't need the resolved URL, so
    # overlapping it removes the join latency from the critical path. Only
    # for fresh playback (an active chat just enqueues, no join needed).
    join_task = (
        asyncio.create_task(ensure_userbot_in_chat(client, message.chat.id))
        if not q.is_active(message.chat.id) else None
    )

    duration = None
    generic_mp4 = False
    if replied_media:
        # The actual file type wins over the command: an mp3 can only be
        # streamed as audio even if the user typed /vplay.
        is_video = replied_is_video
        # Carry the media's own duration so the video EOF watchdog can arm and
        # the premature-stream-end guard uses the real length (documents have
        # none — that's fine, the local-file StreamEnded path still fires).
        duration = getattr(replied_media, "duration", None) or None
        status = await message.reply_text(
            f"{_E_DL} <b>Downloading…</b>", parse_mode=ParseMode.HTML,
        )
        try:
            stream_url = await message.reply_to_message.download(
                file_name=os.path.join(
                    DOWNLOAD_DIR, f"{replied_media.file_unique_id}_"
                )
            )
            info = replied_label
            # A locally uploaded/downloaded VIDEO only carries a UUID-ish
            # filename, never a real title. Flag it so the UI shows a clean,
            # queue-numbered "Mp4 Video[ N]" (queue.display_title) instead of
            # leaking the filename/hash — and keep a clean base title here so
            # nothing downstream (logs included) exposes the raw name.
            if is_video:
                generic_mp4 = True
                info = "Mp4 Video"
        except Exception as exc:
            logger.exception("download of replied media failed")
            await status.edit_text(
                "❌ <b>Download failed</b>\n"
                f"<code>{html.escape(str(exc))}</code>",
                parse_mode=ParseMode.HTML,
            )
            await _log_play(client, message, is_video=is_video, ok=False,
                            title=replied_label, detail=f"download failed: {exc}")
            return
    else:
        query = replied_url if replied_url else " ".join(message.command[1:])
        status = await message.reply_text(
            f"{_E_SEARCH} <b>Searching…</b>", parse_mode=ParseMode.HTML,
        )
        logger.info("resolve(%r, video=%s) for chat=%s", query, is_video, message.chat.id)
        stream_url, info, duration = await resolve(query, video=is_video)
        if not stream_url:
            logger.warning("resolve returned no stream_url for %r — %s", query, info)
            await status.edit_text(
                f"❌ {html.escape(str(info))}", parse_mode=ParseMode.HTML
            )
            await _log_play(client, message, is_video=is_video, ok=False,
                            title=query, detail=str(info))
            return
        logger.info(
            "resolved %r → label=%r url_len=%s url_head=%s",
            query, info, len(stream_url or ""), (stream_url or "")[:80],
        )

    track = q.Track(
        stream_url=stream_url,
        title=info,
        requested_by=_requester_name(message),
        is_video=is_video,
        duration=duration,
        generic_mp4=generic_mp4,
    )
    # Cheap artwork url when the query itself is a YouTube link (no network).
    # Text queries stay None here and resolve lazily by title later, so nothing
    # blocks audio start.
    _m = None if replied_media else _YT_ID_RE.search(query or "")
    if _m:
        track.thumb = f"https://i.ytimg.com/vi/{_m.group(1)}/maxresdefault.jpg"

    # If something is already playing in this chat, just enqueue.
    if q.is_active(message.chat.id):
        position = q.enqueue(message.chat.id, track)
        artist, song = _split_artist(q.display_title(message.chat.id, track))
        eta = _fmt_eta(_queue_eta(message.chat.id, position))
        if track.is_video:
            # Video/MP4 in the queue uses the same dedicated /vplay banner as
            # the Now Playing message. Falls back to the composited card only if
            # the banner asset is missing. Audio is unchanged.
            thumb = thumbnail.default_photo()
            if thumb is None:
                art = await _track_artwork(track)
                thumb = await thumbnail.generate(art, default_when_missing=True)
        else:
            art = await _track_artwork(track)
            thumb = await thumbnail.generate(art)
        caption = render_queue_added(
            song, artist, track.duration, position, eta, track.requested_by,
        )
        await _send_queue_card(client, message, status, caption, position, thumb)
        await _log_play(client, message, is_video=is_video, ok=True,
                        title=info, detail=f"queued #{position}", event="Queue")
        return

    # Fresh playback. The VC join is already running in parallel with resolve
    # (started above). Await it, then hand the resolved URL to play_track,
    # which STREAMS it directly — first audio starts without waiting for a
    # full download (play_track downloads only as a fallback if streaming
    # fails).
    await status.edit_text(
        f"{_E_VC} <b>Connecting…</b>", parse_mode=ParseMode.HTML,
    )
    # Await the join we started in parallel above (fall back to a fresh call
    # if the chat only became inactive after the early check).
    ok, detail = await (join_task or ensure_userbot_in_chat(client, message.chat.id))
    if not ok:
        await status.edit_text(
            f"❌ {html.escape(str(detail))}", parse_mode=ParseMode.HTML
        )
        await _log_play(client, message, is_video=is_video, ok=False,
                        title=info, detail=f"assistant join failed: {detail}")
        return

    logger.info("calling play_track for chat=%s title=%r", message.chat.id, info)
    try:
        await play_track(message.chat.id, track)
    except Exception as exc:
        # TelegramServerError / RPCError subclasses carry .ID and .MESSAGE
        # — surface those so the operator sees CALL_OCCUPY_FAILED /
        # GROUPCALL_INVALID / etc. instead of the bare class name.
        exc_id = getattr(exc, "ID", None)
        exc_msg = getattr(exc, "MESSAGE", None)
        logger.exception(
            "play_track raised: type=%s id=%s message=%s repr=%r",
            type(exc).__name__, exc_id, exc_msg, exc,
        )
        ui_id = f" [{html.escape(str(exc_id))}]" if exc_id else ""
        await status.edit_text(
            "❌ <b>Playback failed</b>\n"
            f"<code>{html.escape(type(exc).__name__)}{ui_id}: "
            f"{html.escape(str(exc_msg or exc))}</code>",
            parse_mode=ParseMode.HTML,
        )
        await _log_play(client, message, is_video=is_video, ok=False, title=info,
                        detail=f"{type(exc).__name__}: {exc_msg or exc}")
        return

    # Render the Now Playing player as ONE media message: composited thumbnail
    # photo + full card as caption + inline controls. Runs AFTER playback
    # started, so thumbnail generation never delays audio.
    await _send_now_playing(client, message.chat.id, track, replace=status)
    await _log_play(client, message, is_video=is_video, ok=True, title=info)
    logger.info("play_track returned cleanly for chat=%s", message.chat.id)


async def _log_play(client, message, *, is_video: bool, ok: bool,
                    title: str, detail: str = "", event: str = "Play") -> None:
    """Best-effort premium event log to the configured log chat. No-op when no
    log chat is set. Delegates to logchannel.log_play_event so the play/vplay/
    queue log matches the other logs' UI (bars + premium emoji + clickable
    by-ID mention)."""
    chat = message.chat
    await log_play_event(
        client,
        user=message.from_user,
        chat_title=getattr(chat, "title", None) or str(getattr(chat, "id", "")),
        chat_id=getattr(chat, "id", ""),
        title=title, is_video=is_video, ok=ok, detail=detail, event=event,
    )


async def _send_queue_card(client, message, status, caption, position, thumb) -> None:
    """Send the 'Added to Queue' card: photo+caption when a thumbnail is
    available (a text message can't be edited into a photo, so the transient
    status is deleted and a fresh photo is sent), else styled text. Never
    raises — falls back through styled→plain keyboard→plain text so the queue
    confirmation always sends."""
    chat_id = message.chat.id
    if thumb:
        try:
            try:
                await status.delete()
            except Exception:
                pass
            await client.send_photo(
                chat_id, thumb, caption=caption, parse_mode=ParseMode.HTML,
                reply_markup=queue_added_keyboard(position, styled=True),
            )
            return
        except Exception as exc:
            logger.warning("queue-card photo failed (%s) — text fallback", exc)
            status = None  # status already deleted; send a fresh message below
    sender = status.edit_text if status else message.reply_text
    for styled in (True, False):
        try:
            await sender(
                caption, parse_mode=ParseMode.HTML,
                reply_markup=queue_added_keyboard(position, styled=styled),
                disable_web_page_preview=True,
            )
            return
        except Exception as exc:
            logger.warning("queue-card text (styled=%s) failed: %s", styled, exc)
    try:
        await sender(caption, parse_mode=ParseMode.HTML,
                     disable_web_page_preview=True)
    except Exception:
        logger.exception("queue-card render failed entirely")


async def _send_now_playing(client, chat_id, track, *, replace=None) -> None:
    """Send the Now Playing player as a SINGLE media message: composited
    thumbnail photo + the full card as its caption + inline controls. `replace`
    is a transient status text message deleted first (a text message can't be
    edited into a photo). Falls back to a text-only player when the photo can't
    be built or sent, so a missing thumbnail never breaks or splits the message."""
    body = render_for_chat(chat_id, track)
    photo = None
    try:
        if track.is_video:
            # /vplay: attach the dedicated video image (bundled asset), not the
            # composited player card. Falls back to the card only if the asset
            # is somehow missing.
            photo = thumbnail.default_photo()
            if photo is None:
                art = await _track_artwork(track)
                photo = await thumbnail.generate(art, default_when_missing=True)
        else:
            # /play (audio): unchanged — the composited Now Playing card.
            art = await _track_artwork(track)
            photo = await thumbnail.generate(art)
    except Exception:
        logger.exception("now-playing thumbnail generation failed")
    if replace is not None:
        try:
            await replace.delete()
        except Exception:
            pass
    if photo is not None:
        for styled in (True, False):
            try:
                await client.send_photo(
                    chat_id, photo, caption=body, parse_mode=ParseMode.HTML,
                    reply_markup=nowplaying_keyboard(styled=styled),
                )
                return
            except Exception as exc:
                logger.warning("now-playing photo (styled=%s) failed: %s", styled, exc)
                try:
                    photo.seek(0)
                except Exception:
                    pass
    for styled in (True, False):
        try:
            await client.send_message(
                chat_id, body, parse_mode=ParseMode.HTML,
                reply_markup=nowplaying_keyboard(styled=styled),
                disable_web_page_preview=True,
            )
            return
        except Exception as exc:
            logger.warning("now-playing text (styled=%s) failed: %s", styled, exc)
    try:
        icon = "🎬" if track.is_video else "🎵"
        await client.send_message(
            chat_id,
            f"{icon} <b>Now Playing</b>\n"
            f"<code>{html.escape(q.display_title(chat_id, track))}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        logger.exception("now-playing render failed entirely")


def _skip_card(track, user, *, queue_empty: bool, title: str = None) -> str:
    """Premium skip confirmation: skipped title, song/video wording (auto-
    detected from the track), and a clickable by-ID mention of the skipper.
    `title` overrides track.title with a resolved display name when provided."""
    is_vid = bool(getattr(track, "is_video", False))
    kind = "Video" if is_vid else "Song"
    tail = "🎬" if is_vid else "🎵"
    _t = title if title is not None else (getattr(track, "title", None) if track else None)
    title = html.escape(_t) if _t else "the current track"
    lines = [
        f"{_E_VC} <b>Skipped</b>",
        f"{tail} <b>{kind}:</b> {title}",
        f"{e.USER} <b>By:</b> {e.mention(user)}",
    ]
    if queue_empty:
        lines.append("<i>Queue's empty — the assistant left the voice chat.</i>")
    return "\n".join(lines)


async def do_skip(client, message):
    """Shared by /skip and /vskip — there's one VC per chat, so audio and
    video share the same queue. Reusing the implementation keeps behavior
    consistent and stops the two from drifting apart.
    """
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await message.reply_text(
            "👥 <b>Groups only</b>\n"
            "<i>/skip works inside a group with an active voice chat.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    if not q.is_active(message.chat.id):
        await message.reply_text(
            f"{_E_HINT} <b>Nothing is playing</b>\n"
            "<i>Start something with /play.</i>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Capture what's being skipped (and who) BEFORE the queue advances — resolve
    # the display title now, while the track is still in the timeline, so a
    # generic MP4 shows its proper "Mp4 Video[ N]".
    skipped = q.now_playing(message.chat.id)
    skipper = message.from_user
    skipped_title = q.display_title(message.chat.id, skipped) if skipped else None

    nxt = q.pop_next(message.chat.id)
    if nxt is None:
        # Queue exhausted — end the session and pull the assistant out
        # of the group, same as a natural stream-end. Anti-misuse.
        await end_session(message.chat.id)
        await message.reply_text(
            _skip_card(skipped, skipper, queue_empty=True, title=skipped_title),
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        await play_track(message.chat.id, nxt)
    except Exception as exc:
        await message.reply_text(
            "❌ <b>Skip failed</b>\n"
            f"<code>{html.escape(f'{type(exc).__name__}: {exc}')}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Enhanced skip confirmation, then the next track's full Now Playing card
    # + controls (existing behaviour preserved).
    await message.reply_text(
        _skip_card(skipped, skipper, queue_empty=False, title=skipped_title),
        parse_mode=ParseMode.HTML,
    )
    await _send_now_playing(client, message.chat.id, nxt)
