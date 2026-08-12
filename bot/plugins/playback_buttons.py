"""Callback handlers for the Now Playing inline control panel.

Callback data layout: mp:<action>
  mp:prev     — step back to the previous track (if history exists)
  mp:toggle   — pause if playing, resume if paused (we don't track
                state explicitly, so we try pause first and fall back
                to resume on failure)
  mp:next     — skip to next track
  mp:skip     — alias of next, kept because the user asked for both
  mp:shuffle  — random-shuffle the upcoming queue
  mp:loop     — toggle the per-chat repeat flag
  mp:stop     — end the session (clears queue, leaves VC + group)

Authorization: any user in the chat may click. Voice-chat controls
have historically been open in this bot's text-command surface so
this matches.

Each handler refreshes the Now Playing message in place when the
visible state (track / repeat) changes.
"""

import html
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InputMediaPhoto

from bot.utils import emoji as e
from bot.utils import music as music_mod
from bot.utils import queue as q
from bot.utils import thumbnail
from bot.utils.np_ui import nowplaying_keyboard, render_for_chat
from bot.utils.playback import end_session, play_track

logger = logging.getLogger("WarbornMusic.playback_buttons")


def _stop_card(track, user, header: str) -> str:
    """Premium session-ended card: title, song/video wording (auto-detected),
    and a clickable by-ID mention of whoever pressed the button."""
    is_vid = bool(getattr(track, "is_video", False))
    kind = "Video" if is_vid else "Song"
    tail = "🎬" if is_vid else "🎵"
    title = html.escape(track.title) if track and getattr(track, "title", None) else "the current track"
    return "\n".join([
        f"⏹️ <b>{header}</b>",
        f"{tail} <b>{kind}:</b> {title}",
        f"{e.USER} <b>By:</b> {e.mention(user)}",
        "<i>The assistant left the voice chat.</i>",
    ])


async def _refresh_card(callback_query, *, update_media: bool = True) -> None:
    """Re-render the Now Playing player in place — never a new message.

    Single media message: when the track changed (update_media), refresh the
    thumbnail via edit_media; otherwise (state toggle) edit just the caption.
    Text-fallback player: edit the text. MessageNotModified is harmless."""
    chat_id = callback_query.message.chat.id
    cur = q.now_playing(chat_id)
    if cur is None:
        return
    body = render_for_chat(chat_id, cur)
    msg = callback_query.message
    is_photo = bool(getattr(msg, "photo", None))
    try:
        if is_photo and update_media:
            photo = None
            try:
                if cur.is_video:
                    # Keep the /vplay message on its dedicated video image.
                    photo = thumbnail.default_photo()
                    if photo is None:
                        from bot.utils.play_actions import _track_artwork
                        photo = await thumbnail.generate(
                            await _track_artwork(cur), default_when_missing=True
                        )
                else:
                    from bot.utils.play_actions import _track_artwork
                    photo = await thumbnail.generate(await _track_artwork(cur))
            except Exception:
                logger.exception("refresh_card: thumbnail regen failed")
            if photo is not None:
                await msg.edit_media(
                    InputMediaPhoto(photo, caption=body, parse_mode=ParseMode.HTML),
                    reply_markup=nowplaying_keyboard(),
                )
                return
        if is_photo:
            await msg.edit_caption(
                body, parse_mode=ParseMode.HTML, reply_markup=nowplaying_keyboard(),
            )
        else:
            await msg.edit_text(
                body, parse_mode=ParseMode.HTML,
                reply_markup=nowplaying_keyboard(), disable_web_page_preview=True,
            )
    except Exception as exc:
        # MessageNotModified is harmless. Anything else we just log.
        if "MESSAGE_NOT_MODIFIED" not in str(exc).upper():
            logger.info("refresh_card edit failed: %s", exc)


async def _end_card(callback_query, text: str) -> None:
    """Edit the player into an end/stop card in place, dropping the controls.
    Caption for the media player, text for the fallback player."""
    msg = callback_query.message
    try:
        if getattr(msg, "photo", None):
            await msg.edit_caption(text, parse_mode=ParseMode.HTML, reply_markup=None)
        else:
            await msg.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=None)
    except Exception:
        pass


@Client.on_callback_query(filters.regex(r"^mp:(prev|toggle|next|skip|shuffle|loop|stop)$"))
async def mp_callback(client, callback_query):
    action = callback_query.data.split(":", 1)[1]
    chat_id = callback_query.message.chat.id if callback_query.message and callback_query.message.chat else None

    if chat_id is None:
        await callback_query.answer("Lost the chat — try /play again.", show_alert=True)
        return

    if not q.is_active(chat_id) and action not in ("stop",):
        await callback_query.answer("Nothing is playing.", show_alert=False)
        return

    music = music_mod.music

    try:
        if action == "toggle":
            # Try pause; if py-tgcalls reports "not paused" we treat it
            # as a resume request. Different py-tgcalls versions raise
            # different exception classes, so go by message.
            try:
                await music.pause(chat_id)
                await callback_query.answer("Paused.")
            except Exception as exc:
                msg = str(exc).lower()
                if "paused" in msg or "not playing" in msg or "already" in msg:
                    try:
                        await music.resume(chat_id)
                        await callback_query.answer("Resumed.")
                    except Exception as exc2:
                        await callback_query.answer(f"Resume failed: {exc2}", show_alert=True)
                else:
                    await callback_query.answer(f"Pause failed: {exc}", show_alert=True)
            return

        if action in ("next", "skip"):
            ending = q.now_playing(chat_id)
            nxt = q.pop_next(chat_id)
            if nxt is None:
                await end_session(chat_id)
                await callback_query.answer("Queue empty — left the voice chat.", show_alert=False)
                await _end_card(callback_query, _stop_card(ending, callback_query.from_user, "Playback Ended"))
                return
            await play_track(chat_id, nxt)
            await callback_query.answer(f"Skipped → {nxt.title[:40]}")
            await _refresh_card(callback_query)
            return

        if action == "prev":
            prev = q.pop_history(chat_id)
            if prev is None:
                await callback_query.answer("No previous track.", show_alert=False)
                return
            await play_track(chat_id, prev)
            await callback_query.answer(f"Rewound → {prev.title[:40]}")
            await _refresh_card(callback_query)
            return

        if action == "shuffle":
            n = q.shuffle_upcoming(chat_id)
            if n < 2:
                await callback_query.answer("Need at least 2 upcoming tracks to shuffle.", show_alert=False)
                return
            await callback_query.answer(f"Shuffled {n} upcoming tracks.")
            return

        if action == "loop":
            new = q.toggle_repeat(chat_id)
            await callback_query.answer(f"Repeat: {'ON' if new else 'OFF'}.")
            await _refresh_card(callback_query, update_media=False)
            return

        if action == "stop":
            stopped = q.now_playing(chat_id)
            await end_session(chat_id)
            await callback_query.answer("Stopped. Left the voice chat.")
            await _end_card(callback_query, _stop_card(stopped, callback_query.from_user, "Playback Stopped"))
            return

    except Exception as exc:
        logger.exception("mp callback %s failed", action)
        await callback_query.answer(f"{type(exc).__name__}: {exc}", show_alert=True)


@Client.on_callback_query(filters.regex(r"^mp:queue$"))
async def mp_queue(client, callback_query):
    """📜 Queue button — compact popup of the current + upcoming tracks."""
    chat_id = callback_query.message.chat.id if callback_query.message and callback_query.message.chat else None
    cur = q.now_playing(chat_id) if chat_id is not None else None
    up = q.upcoming(chat_id) if chat_id is not None else []
    if not cur and not up:
        await callback_query.answer("Queue is empty.", show_alert=True)
        return
    lines = []
    if cur:
        lines.append(f"▶ {cur.title[:40]}")
    for i, t in enumerate(up[:8], start=1):
        lines.append(f"{i}. {t.title[:40]}")
    extra = len(up) - 8
    if extra > 0:
        lines.append(f"… +{extra} more")
    await callback_query.answer("\n".join(lines)[:200], show_alert=True)


@Client.on_callback_query(filters.regex(r"^mp:chgsong:(\d+)$"))
async def mp_chgsong(client, callback_query):
    """🔄 Change Song button — remove this queued track so the requester can
    /play a different one."""
    chat_id = callback_query.message.chat.id if callback_query.message and callback_query.message.chat else None
    pos = int(callback_query.data.split(":", 2)[2])
    removed = q.remove_at(chat_id, pos) if chat_id is not None else None
    if not removed:
        await callback_query.answer("That track is no longer in the queue.", show_alert=True)
        return
    await callback_query.answer(
        f"Removed “{removed.title[:40]}”. Send /play to queue a different song.",
        show_alert=True,
    )
    try:
        await callback_query.message.delete()
    except Exception:
        pass
