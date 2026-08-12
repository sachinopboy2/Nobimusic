"""Single entry point that hands a `Track` to py-tgcalls and reacts to
stream-end events by advancing the per-chat queue.

The PyTgCalls instance is constructed lazily inside the running event
loop (see bot.utils.music.init). This module therefore:
- Accesses `music` via the module attribute (`music_mod.music`) instead
  of name-binding it at import time — so it always sees the live
  instance.
- Registers the @on_update stream-end handler in `register_handlers()`,
  which is called from bot.start._run AFTER init.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import time

import aiohttp
from pytgcalls.types import AudioQuality, MediaStream

try:
    from pytgcalls.types import VideoQuality  # type: ignore
except Exception:  # pragma: no cover
    VideoQuality = None  # type: ignore

from bot.client import userbot
from bot.utils import music as music_mod
from bot.utils import queue as q

logger = logging.getLogger("WarbornMusic.playback")

# Download-first cache. Playing from a local file instead of streaming a live
# remote URL removes CDN/network buffering during playback. Files are per-chat
# and reaped when the next track plays or the session ends.
_PLAY_CACHE_DIR = "/tmp/warborn_playcache"
_chat_media: dict[int, str] = {}

# monotonic timestamp when the current track started, per chat — used to
# ignore premature StreamEnded events (transient CDN drop / spurious ntgcalls
# event) that would otherwise wrongly advance the queue or leave the call.
_started_at: dict[int, float] = {}


def get_started_at(chat_id: int):
    """Read-only: monotonic start time of the chat's current track, or None.
    Used only for the queue-card ETA estimate; does not mutate any state."""
    return _started_at.get(chat_id)


# Per-chat EOF watchdog tasks + advance locks. The watchdog is a fallback for
# when py-tgcalls doesn't fire StreamEnded (notably finite video streams): it
# polls the actual played time and completes the track when it reaches the
# known duration. The lock makes completion run exactly once whether it's
# triggered by StreamEnded or the watchdog.
_watchdogs: dict[int, "asyncio.Task"] = {}
_advance_locks: dict[int, "asyncio.Lock"] = {}
# Whether the current track plays from a LOCAL file (True) or a live URL
# (False). A StreamEnded on a local file is authoritative (ffmpeg EOF = real
# end), so the premature-end guard — which exists only to absorb transient
# CDN drops on streamed URLs — must not suppress it.
_src_is_local: dict[int, bool] = {}
# Cached userbot identity — never changes for the process, so avoid a get_me()
# round-trip on every play (shaves latency off the VC-join path).
_userbot_me = None
# Chats whose peer the userbot has already primed this session — skip the
# get_chat() round-trip on subsequent plays to shave join latency.
_primed_chats: set[int] = set()


async def _get_userbot_me():
    global _userbot_me
    if _userbot_me is None:
        _userbot_me = await userbot.get_me()
    return _userbot_me
# How many seconds before a track's known duration a StreamEnded is treated as
# genuine. Ends earlier than this are considered premature and ignored.
_END_GRACE_S = 15
# Fallback floor when the track's duration is unknown: a StreamEnded within this
# many seconds of start is treated as premature (spurious ntgcalls event / stale
# post-/skip event) rather than a real end — so the assistant doesn't leave a
# song it only just started.
_MIN_PLAY_S = 30


# Parallel download tuning. YouTube throttles per CONNECTION, so pulling the
# file over several byte-range requests at once is far faster than one stream.
_DL_CONNECTIONS = 8
_DL_PARALLEL_MIN = 1 << 20  # only split files larger than 1 MiB
_DL_TIMEOUT = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=30)


async def _fetch_range(s, url, path, start, end) -> None:
    """Download bytes [start, end] into `path` at the right offset."""
    async with s.get(url, headers={"Range": f"bytes={start}-{end}"}) as r:
        if r.status != 206:
            raise RuntimeError(f"range not honored (HTTP {r.status})")
        pos = start
        with open(path, "r+b") as fh:
            fh.seek(start)
            async for chunk in r.content.iter_chunked(1 << 18):
                fh.write(chunk)
                pos += len(chunk)
    if pos - 1 != end:
        raise RuntimeError(f"short range: got {pos - start}, want {end - start + 1}")


async def _download_ranged(s, url, path, total, conns) -> bool:
    """Fetch `total` bytes over `conns` concurrent range requests. True if the
    reassembled file is complete."""
    part = (total + conns - 1) // conns
    ranges, start = [], 0
    while start < total:
        end = min(start + part, total) - 1
        ranges.append((start, end))
        start = end + 1
    with open(path, "wb") as fh:  # preallocate so each task seeks into place
        fh.truncate(total)
    await asyncio.gather(*(_fetch_range(s, url, path, a, b) for a, b in ranges))
    return os.path.getsize(path) == total


async def _download_single(s, url, path) -> str | None:
    async with s.get(url) as r:
        if r.status != 200:
            logger.warning("play download HTTP %s for %s", r.status, url[:80])
            return None
        expected = r.content_length
        with open(path, "wb") as fh:
            async for chunk in r.content.iter_chunked(1 << 18):
                fh.write(chunk)
    size = os.path.getsize(path)
    if size == 0:
        return None
    # Truncated fetch (CDN closed early) — discard so the caller streams instead.
    if expected and size < expected:
        logger.warning("play download truncated (%s/%s bytes) — will stream instead", size, expected)
        return None
    return path


async def download_media(url: str, is_video: bool) -> str | None:
    """Download a remote media URL to a local temp file (best-effort).

    Uses parallel byte-range requests to beat YouTube's per-connection
    throttle, falling back to a single stream when the server doesn't support
    ranges. Returns the local path, or None on failure so the caller can fall
    back to live streaming."""
    try:
        os.makedirs(_PLAY_CACHE_DIR, exist_ok=True)
        fd, path = tempfile.mkstemp(
            dir=_PLAY_CACHE_DIR, suffix=".mp4" if is_video else ".m4a"
        )
        os.close(fd)
    except OSError as exc:
        logger.warning("play cache mkstemp failed: %s", exc)
        return None
    try:
        async with aiohttp.ClientSession(timeout=_DL_TIMEOUT) as s:
            # Probe total size + range support with a 1-byte request.
            total, ranged = None, False
            try:
                async with s.get(url, headers={"Range": "bytes=0-0"}) as r:
                    if r.status == 206:
                        cr = r.headers.get("Content-Range", "")
                        tail = cr.rsplit("/", 1)[-1] if "/" in cr else ""
                        if tail.isdigit():
                            total, ranged = int(tail), True
                    elif r.status != 200:
                        logger.warning("play download probe HTTP %s for %s", r.status, url[:80])
                        os.remove(path)
                        return None
            except Exception as exc:
                logger.info("play download range-probe failed (%s) — single stream", exc)

            if ranged and total and total > _DL_PARALLEL_MIN:
                try:
                    if await _download_ranged(s, url, path, total, _DL_CONNECTIONS):
                        return path
                    logger.info("ranged download incomplete — falling back to single stream")
                except Exception as exc:
                    logger.info("ranged download failed (%s) — single stream", exc)

            result = await _download_single(s, url, path)
            if result:
                return result
            os.remove(path)
            return None
    except Exception as exc:
        logger.warning("play download failed (%s) — will stream instead", exc)
        try:
            os.remove(path)
        except OSError:
            pass
        return None


def _cancel_watchdog(chat_id: int) -> None:
    t = _watchdogs.pop(chat_id, None)
    if t is not None:
        t.cancel()


def _forget_media(chat_id: int) -> None:
    """Delete and forget the cached media file for a chat."""
    _cancel_watchdog(chat_id)
    _started_at.pop(chat_id, None)
    _src_is_local.pop(chat_id, None)
    p = _chat_media.pop(chat_id, None)
    if p:
        try:
            os.remove(p)
        except OSError:
            pass


def purge_orphan_media() -> tuple[int, int]:
    """Delete cached play-files that are NOT backing a live stream. Used by
    /refresh; never touches a file still referenced by an active track, so
    playback is never interrupted. Returns (files_removed, bytes_freed)."""
    keep = set(_chat_media.values()) | q.active_sources()
    removed = freed = 0
    try:
        names = os.listdir(_PLAY_CACHE_DIR)
    except OSError:
        return 0, 0
    for name in names:
        p = os.path.join(_PLAY_CACHE_DIR, name)
        if p in keep:
            continue
        try:
            sz = os.path.getsize(p)
            os.remove(p)
            removed += 1
            freed += sz
        except OSError:
            pass
    return removed, freed


async def end_session(chat_id: int) -> None:
    """End the VC session for `chat_id`: clear the queue and leave the voice
    call, but STAY a member of the group.

    The assistant no longer leaves the group on session end — rejoining the
    group each /play was slow and rate-limit-prone (FloodWait). Staying in
    means the next /play rejoins the CALL near-instantly, and the userbot
    keeps receiving ChatMemberUpdated events so greetings/departures keep
    working between sessions.

    Best-effort throughout. Logs but never raises.
    """
    try:
        q.clear(chat_id)
    except Exception:
        logger.exception("end_session: queue.clear failed for %s", chat_id)
    _forget_media(chat_id)

    if music_mod.music is not None:
        try:
            await music_mod.music.leave_call(chat_id)
        except Exception as exc:
            # Most common: NotInGroupCallError — VC already ended on its own.
            logger.info("end_session: leave_call(%s) noop/err: %s", chat_id, exc)


async def clear_queue(chat_id: int) -> None:
    """Wipe the per-chat queue and stop the current stream, but leave the
    assistant in the group (unlike end_session, which also ejects it).

    For /clearqueue: a full reset of playback state when a stream died
    without firing StreamEnded (e.g. the assistant was kicked mid-call),
    leaving a phantom "current" track that made is_active() stay True.
    Best-effort; never raises.
    """
    try:
        q.clear(chat_id)
    except Exception:
        logger.exception("clear_queue: queue.clear failed for %s", chat_id)
    _forget_media(chat_id)
    if music_mod.music is not None:
        try:
            await music_mod.music.leave_call(chat_id)
        except Exception as exc:
            logger.info("clear_queue: leave_call(%s) noop/err: %s", chat_id, exc)


async def ensure_userbot_in_chat(client_app, chat_id: int) -> tuple[bool, str]:
    """Make sure the userbot is a member of `chat_id`. Returns (ok, detail).

    Two paths, picked by chat visibility:
      • Public chat (chat.username set) → userbot.join_chat(username).
        No dependence on the BOT's invite-link rights — a username is a
        public address any account can use to walk in.
      • Private chat (no username) → bot exports an invite link, userbot
        joins via the link. Requires the bot to be admin with invite
        rights, hence the older code's failure mode.

    Public-path failures get logged with exc type+message so we can tell
    a Telegram per-account cap (TooManyChannels, FloodWait) apart from a
    chat-side restriction (CHAT_INVALID, USERNAME_INVALID).
    """
    from pyrogram.enums import ChatMemberStatus

    try:
        me = await _get_userbot_me()
        member = await userbot.get_chat_member(chat_id, me.id)
        if member.status not in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
            return True, "already a member"
    except Exception as exc:
        logger.debug("ensure_userbot_in_chat: presence probe failed: %s", exc)

    username = None
    try:
        chat = await client_app.get_chat(chat_id)
        username = getattr(chat, "username", None)
    except Exception as exc:
        logger.debug("ensure_userbot_in_chat: get_chat(%s) failed: %s", chat_id, exc)

    if username:
        try:
            await userbot.join_chat(username)
            logger.info("ensure_userbot_in_chat: userbot joined %s via username @%s", chat_id, username)
            return True, "joined via username"
        except Exception as exc:
            logger.warning(
                "ensure_userbot_in_chat: username join failed for %s (@%s): %s: %s",
                chat_id, username, type(exc).__name__, exc,
            )
            # Don't fall through to invite link for public chats — if the
            # username path failed, the cause is almost certainly per-
            # account (rate limit, channel cap, ban) and inviting via a
            # link won't help. Surface that to the operator.
            return False, (
                f"Assistant couldn't join @{username}: {type(exc).__name__}: {exc}\n"
                "Likely cause: the assistant account is rate-limited, "
                "hit the per-account group cap, or is banned from this chat."
            )

    # Private chat: create a DIRECT-join link (creates_join_request=False) so the
    # assistant walks straight in even when the group has "Approve new members"
    # enabled. export_chat_invite_link returns the *primary* link, which in an
    # approval-gated group only files a pending request — the assistant never
    # actually joins, which is why auto-invite "failed" despite invite rights.
    try:
        from pyrogram.errors import UserAlreadyParticipant
    except Exception:
        UserAlreadyParticipant = ()

    invite = None
    try:
        cil = await client_app.create_chat_invite_link(chat_id, creates_join_request=False)
        invite = getattr(cil, "invite_link", None) or cil
    except Exception as exc:
        logger.debug("ensure_userbot_in_chat: create_chat_invite_link(%s) failed (%s); export fallback", chat_id, exc)
        try:
            invite = await client_app.export_chat_invite_link(chat_id)
        except Exception as exc2:
            logger.warning("ensure_userbot_in_chat: no invite link for %s: %s: %s", chat_id, type(exc2).__name__, exc2)
            return False, (
                f"Assistant isn't in the group and I couldn't create an invite link: {type(exc2).__name__}: {exc2}\n"
                "Make me an admin with 'Invite Users via Link' rights, or invite the assistant account manually."
            )

    try:
        await userbot.join_chat(invite)
        logger.info("ensure_userbot_in_chat: userbot joined %s via invite link", chat_id)
        return True, "joined via invite link"
    except UserAlreadyParticipant:
        return True, "already a member"
    except Exception as exc:
        # Approval-gated group: the join may be pending. Approve it as bot admin.
        try:
            me = await _get_userbot_me()
            await client_app.approve_chat_join_request(chat_id, me.id)
            logger.info("ensure_userbot_in_chat: approved pending join request for userbot in %s", chat_id)
            return True, "joined via invite link (approved request)"
        except Exception as exc2:
            logger.warning(
                "ensure_userbot_in_chat: invite-link join failed for %s: %s: %s; approve fallback: %s",
                chat_id, type(exc).__name__, exc, exc2,
            )
            return False, (
                f"Assistant couldn't join via invite link: {type(exc).__name__}: {exc}\n"
                "Make me an admin with 'Invite Users via Link' rights, or invite the assistant account manually."
            )


def _build_stream(src: str, is_video: bool) -> MediaStream:
    # Remote URLs (YouTube adaptive/googlevideo) get throttled and return a
    # mid-stream 403 when their token expires — ffmpeg then EOFs, so the track
    # "stops halfway" and the assistant leaves. py-tgcalls already passes
    # -reconnect/-reconnect_streamed for URLs but NOT HTTP-error reconnect;
    # add that + a read timeout so a 403/stall reconnects instead of ending.
    # -thread_queue_size buffers more input packets so bursty/jittery network
    # reads (CDN throttling, VPS CPU spikes) don't underrun the call — cuts
    # the "slight buffering" without delaying start (input option, before -i).
    # Reconnect/buffer flags only matter when streaming a live URL; a local
    # file (download-first) needs none.
    is_url = src.startswith(("http://", "https://"))
    # Input-side resilience (local + URL):
    #   -nostdin                    ffmpeg never blocks waiting on stdin
    #   -thread_queue_size 8192     absorb bursty/jittery reads without underrun
    #   -fflags +discardcorrupt     drop a corrupt packet instead of stalling
    #           +genpts             rebuild timestamps → monotonic audio clock
    # URL only adds HTTP-error reconnect + a long IO timeout so a brief network
    # stall or a token-expiry 403 reconnects instead of ending the track.
    inp = ["-nostdin", "-thread_queue_size 8192", "-fflags +discardcorrupt+genpts"]
    if is_url:
        inp.append("-reconnect_on_http_error 4xx,5xx -rw_timeout 30000000")
    # Video reuses the input flags only (no audio filter).
    ff = " ".join(inp) if is_url else None
    # Audio track: explicitly IGNORE video. Without this, py-tgcalls'
    # default video_flags=AUTO_DETECT probes the file for a video stream;
    # for an mp3/voice file that leaves the assistant joined to the call
    # with an empty video pipeline — the "joins the VC but nothing plays"
    # symptom. IGNORE forces a clean audio-only stream.
    if not is_video:
        # `-atmid` puts what follows AFTER -i (output side).
        #   -vn                      skip any video decode (less CPU on
        #                            progressive sources; no quality change)
        #   aresample=async=1        keep the audio clock monotonic, padding
        #                            micro-gaps with silence — the core
        #                            anti-jitter/stutter measure
        audio_ff = " ".join(inp) + " -atmid -vn -af aresample=async=1"
        return MediaStream(
            src,
            audio_parameters=AudioQuality.HIGH,
            video_flags=MediaStream.Flags.IGNORE,
            ffmpeg_parameters=audio_ff,
        )
    # Video track: auto-detect the video stream (falls back to audio-only
    # cleanly if the file happens to have none).
    if VideoQuality is not None:
        return MediaStream(
            src,
            audio_parameters=AudioQuality.HIGH,
            video_parameters=VideoQuality.HD_720p,
            video_flags=MediaStream.Flags.AUTO_DETECT,
            ffmpeg_parameters=ff,
        )
    return MediaStream(
        src,
        audio_parameters=AudioQuality.HIGH,
        video_flags=MediaStream.Flags.AUTO_DETECT,
        ffmpeg_parameters=ff,
    )


async def _play_src(chat_id: int, track: q.Track, src: str) -> None:
    """Hand ONE media source (a URL or a local path) to py-tgcalls and, on
    success, update queue state + reap the previous cached file."""
    is_url = src.startswith(("http://", "https://"))
    on_disk = (not is_url) and bool(src) and os.path.exists(src)
    logger.info("music.play(chat=%s) video=%s is_url=%s on_disk=%s src_head=%s",
                chat_id, track.is_video, is_url, on_disk, src[:120])
    await music_mod.music.play(chat_id, _build_stream(src, track.is_video))
    q.set_current(chat_id, track)
    _started_at[chat_id] = time.monotonic()
    _src_is_local[chat_id] = not is_url
    # Reap the previous cached file; remember the new one only if we played
    # from the download cache (fallback path). A streamed URL caches nothing.
    new_tmp = src if src.startswith(_PLAY_CACHE_DIR) else None
    prev_tmp = _chat_media.get(chat_id)
    if new_tmp:
        _chat_media[chat_id] = new_tmp
    else:
        _chat_media.pop(chat_id, None)
    if prev_tmp and prev_tmp != new_tmp:
        try:
            os.remove(prev_tmp)
        except OSError:
            pass


async def play_track(chat_id: int, track: q.Track) -> None:
    """Start or replace playback for this chat.

    Audio: stream the resolved URL directly (fast), download only as a
    fallback if streaming fails.
    Video: download to a local file first. py-tgcalls adds -reconnect_at_eof
    for URL sources, so a finite video streamed from a URL never signals EOF —
    it ends on a frozen last frame and the StreamEnded/auto-leave event never
    fires. A local file EOFs cleanly, so the assistant auto-advances/leaves.
    """
    if chat_id not in _primed_chats:
        try:
            await userbot.get_chat(chat_id)
            _primed_chats.add(chat_id)
        except Exception as exc:
            logger.warning("userbot.get_chat(%s) failed before play: %s", chat_id, exc)

    src = track.stream_url or ""
    is_url = src.startswith(("http://", "https://"))
    if is_url and track.is_video:
        local = await download_media(src, True)
        if local:
            src, is_url = local, False
    try:
        await _play_src(chat_id, track, src)
    except Exception as exc:
        if not is_url:
            logger.exception("play_track: local source failed chat=%s", chat_id)
            raise
        logger.warning(
            "play_track: stream-first failed chat=%s (%s: %s) — downloading then retrying",
            chat_id, type(exc).__name__, exc,
        )
        local = await download_media(src, track.is_video)
        if not local:
            raise
        # The failed first attempt (or a prior call that never left cleanly)
        # can leave a half-initialized ntgcalls connection, so the retry's
        # create_call raises "Connection cannot be initialized more than once".
        # Force a clean teardown before re-initializing.
        try:
            await music_mod.music.leave_call(chat_id)
        except Exception as le:
            logger.info("play_track: pre-retry leave_call(%s) noop/err: %s", chat_id, le)
        await _play_src(chat_id, track, local)
    logger.info("play_track: playback started for chat=%s", chat_id)

    # Video: arm the EOF watchdog so the assistant leaves when the video ends
    # even if py-tgcalls never fires StreamEnded for it. Audio is left to the
    # existing StreamEnded path (unchanged).
    if track.is_video and track.duration:
        _arm_watchdog(chat_id, _started_at.get(chat_id), track.duration)


async def _announce_now_playing(chat_id: int, track: q.Track) -> None:
    """Post a fresh Now Playing card when the queue auto-advances, so a
    queued song announces itself the same way /play and /skip do. Best-effort
    — never raises into the stream-end handler."""
    try:
        from bot.client import app
        from bot.utils.play_actions import _send_now_playing
        await _send_now_playing(app, chat_id, track)
    except Exception:
        logger.exception("now-playing announce failed for chat %s", chat_id)


def _is_stream_end(update) -> bool:
    """Version-tolerant check for py-tgcalls stream-end events.

    py-tgcalls renames these types across minor versions; the class name
    is stable enough for routing.
    """
    name = type(update).__name__
    return name in ("StreamAudioEnded", "StreamVideoEnded", "StreamEnded")


async def _advance_or_end(chat_id: int) -> None:
    """Advance the queue (or end the session) after a track finishes.
    Unchanged behaviour — extracted so both the StreamEnded handler and the
    EOF watchdog can drive it."""
    # Repeat-current short-circuits the queue advance entirely.
    if q.get_repeat(chat_id):
        cur = q.now_playing(chat_id)
        if cur is not None:
            try:
                await play_track(chat_id, cur)
            except Exception:
                logger.exception("Repeat-replay failed for chat %s", chat_id)
                await end_session(chat_id)
            return

    nxt = q.pop_next(chat_id)
    if nxt is None:
        # Queue exhausted: end the session and leave the call.
        await end_session(chat_id)
        return

    played = None
    try:
        await play_track(chat_id, nxt)
        played = nxt
    except Exception:
        logger.exception("Auto-advance failed for chat %s", chat_id)
        further = q.pop_next(chat_id)
        if further is not None:
            try:
                await play_track(chat_id, further)
                played = further
            except Exception:
                logger.exception("Second-chance auto-advance also failed")
    if played is not None:
        await _announce_now_playing(chat_id, played)


async def _complete_track(chat_id: int, token) -> None:
    """Run the end-of-track advance/leave EXACTLY ONCE for the track that
    started at `token` (its _started_at value). Whichever trigger arrives
    first — StreamEnded or the EOF watchdog — wins; the other sees a changed
    _started_at and no-ops."""
    if token is None:
        return
    lock = _advance_locks.setdefault(chat_id, asyncio.Lock())
    async with lock:
        if _started_at.get(chat_id) != token:
            return
        await _advance_or_end(chat_id)


async def _eof_watchdog(chat_id: int, token, duration: int) -> None:
    """Fallback end-of-media detector for streams that don't fire StreamEnded
    (finite video makes py-tgcalls add -reconnect_at_eof, so EOF never
    surfaces). Polls the ACTUAL played time — which stalls while paused, so
    this never cuts a paused track — and completes when it reaches duration."""
    try:
        while True:
            await asyncio.sleep(4)
            if _started_at.get(chat_id) != token:
                return  # track was replaced — this watchdog is stale
            try:
                played = await music_mod.music.time(chat_id)
            except Exception:
                played = None  # not/no longer in the call → treat as ended
            if played is None or played >= duration - 2:
                break
        if _started_at.get(chat_id) != token or not q.is_active(chat_id):
            return
        logger.warning(
            "playback: EOF watchdog completing chat=%s (StreamEnded not received)",
            chat_id)
        await _complete_track(chat_id, token)
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception("EOF watchdog error chat=%s", chat_id)


def _arm_watchdog(chat_id: int, token, duration: int) -> None:
    _cancel_watchdog(chat_id)
    _watchdogs[chat_id] = asyncio.create_task(_eof_watchdog(chat_id, token, duration))


async def _on_pytgcalls_update(_, update) -> None:
    if not _is_stream_end(update):
        return
    chat_id = getattr(update, "chat_id", None)
    if chat_id is None:
        return

    # Premature stream-end guard. A transient network drop, a stale event from
    # a just-replaced stream (e.g. right after /skip), or an ntgcalls hiccup
    # can fire StreamEnded well before the track actually finished. If the
    # current track's known duration says we ended too early, ignore it.
    cur = q.now_playing(chat_id)
    dur = getattr(cur, "duration", None) if cur is not None else None
    started = _started_at.get(chat_id)
    # Only guard streamed URLs: a local-file StreamEnded (replied/downloaded
    # video) is a real end, so trust it immediately and leave the call.
    if started is not None and not _src_is_local.get(chat_id, False):
        elapsed = time.monotonic() - started
        premature = (elapsed + _END_GRACE_S < dur) if dur else (elapsed < _MIN_PLAY_S)
        if premature:
            logger.warning(
                "playback: ignoring premature stream-end chat=%s "
                "(played %.0fs, dur=%s)", chat_id, elapsed, dur)
            return

    await _complete_track(chat_id, started)


def register_handlers() -> None:
    """Register the stream-end auto-advance on the live music instance.

    Called from bot.start._run after bot.utils.music.init has constructed
    PyTgCalls. Equivalent to the old `@music.on_update()` module-level
    decorator, but deferred so the music instance actually exists.
    """
    if music_mod.music is None:
        raise RuntimeError(
            "playback.register_handlers called before music.init"
        )
    music_mod.music.on_update()(_on_pytgcalls_update)
