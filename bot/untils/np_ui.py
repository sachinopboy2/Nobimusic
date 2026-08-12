"""Now-playing message renderer + control keyboard.

Layout matches the user-supplied mockup: boxed header, track block,
static progress bar, decorative control row with premium custom emoji,
requester / repeat footer box.

Telegram custom-emoji uses pyrofork's <emoji id="...">FALLBACK</emoji>
syntax (not <custom_emoji ...>). Fallback glyphs are visible on clients
without premium-emoji support.

The progress bar is intentionally static. Real-time updates would
require either an in-process tick task per chat or repeated message
edits, both of which break Telegram's edit rate limits in heavy use.
"""

import html

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.utils import emoji as e
from bot.utils import queue as q

# Static 14-cell progress bar — "▰▰▰▰▱▱▱▱▱▱▱▱▱▱". Sender sees a fresh
# render, so we always start the indicator near the head of the track.
_PROGRESS_BAR = "▰▰▰▰▱▱▱▱▱▱▱▱▱▱"


def _fmt_dur(seconds) -> str:
    if not seconds or seconds <= 0:
        return "LIVE"
    s = int(seconds)
    if s < 3600:
        return f"{s // 60}:{s % 60:02d}"
    return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _card(track, repeat: str, duration=None, title: str = None) -> str:
    """Compact Now Playing card (4 lines). Premium custom emoji with
    unicode fallbacks; title/requester HTML-escaped so odd characters
    can't break the parse. `title` overrides track.title when the caller
    resolved a display name (e.g. the dynamic "Mp4 Video N")."""
    title = html.escape(((title if title is not None else track.title) or "Unknown title").strip())
    requester = html.escape((track.requested_by or "someone").strip())
    end = _fmt_dur(duration if duration is not None else getattr(track, "duration", None))
    return (
        f"{e.HEAD} <b>Now Playing</b>\n"
        f"<b>{title}</b>\n"
        f"<code>{_PROGRESS_BAR}  0:00 / {end}</code>\n"
        f"{e.USER} {requester}   "
        f"{e.CHECK} {repeat}"
    )


def render_now_playing(track, duration=None) -> str:
    """Compact Now Playing caption. Repeat defaults to OFF — callers that
    know the chat should use render_for_chat."""
    return _card(track, "OFF", duration)


def render_for_chat(chat_id: int, track, duration=None) -> str:
    """Same as render_now_playing but reads the chat's repeat flag and resolves
    the dynamic display title (clean "Mp4 Video N" for generic local MP4s)."""
    return _card(track, "ON" if q.get_repeat(chat_id) else "OFF", duration,
                 title=q.display_title(chat_id, track))


def nowplaying_keyboard(styled: bool = True) -> InlineKeyboardMarkup:
    """Inline controls under the Now Playing message.

    Layout (3+3+2 buttons — compact & balanced):
      [Prev] [Play] [Next]
      [Shuffle] [Loop] [Stop]
      [Skip] [Menu]

    `styled=True` (default) uses the 2026 coloured ButtonStyle + premium
    custom-emoji icons. If a client/bot can't render those and the send
    is rejected, the caller retries with `styled=False` — the same buttons
    with plain text/no colour — so the controls never disappear.
    """
    if not styled:
        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Prev", callback_data="mp:prev"),
                    InlineKeyboardButton("Play", callback_data="mp:toggle"),
                    InlineKeyboardButton("Next", callback_data="mp:next"),
                ],
                [
                    InlineKeyboardButton("Shuffle", callback_data="mp:shuffle"),
                    InlineKeyboardButton("Loop", callback_data="mp:loop"),
                    InlineKeyboardButton("Stop", callback_data="mp:stop"),
                ],
                [
                    InlineKeyboardButton("Skip", callback_data="mp:skip"),
                    InlineKeyboardButton("Menu", callback_data="mp:menu"),
                ],
            ]
        )

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Prev", callback_data="mp:prev",
                                     icon_custom_emoji_id=e.NOTE_ID,
                                     style=ButtonStyle.PRIMARY),
                InlineKeyboardButton("Play", callback_data="mp:toggle",
                                     icon_custom_emoji_id=e.MUSIC_ID,
                                     style=ButtonStyle.SUCCESS),
                InlineKeyboardButton("Next", callback_data="mp:next",
                                     icon_custom_emoji_id=e.BOLT_ID,
                                     style=ButtonStyle.PRIMARY),
            ],
            [
                InlineKeyboardButton("Shuffle", callback_data="mp:shuffle",
                                     icon_custom_emoji_id=e.DICE_ID,
                                     style=ButtonStyle.PRIMARY),
                InlineKeyboardButton("Loop", callback_data="mp:loop",
                                     icon_custom_emoji_id=e.CHECK_ID,
                                     style=ButtonStyle.SUCCESS),
                InlineKeyboardButton("Stop", callback_data="mp:stop",
                                     icon_custom_emoji_id=e.NO_ENTRY_ID,
                                     style=ButtonStyle.DANGER),
            ],
            [
                InlineKeyboardButton("Skip", callback_data="mp:skip",
                                     icon_custom_emoji_id=e.BOLT2_ID,
                                     style=ButtonStyle.DANGER),
                InlineKeyboardButton("Menu", callback_data="mp:menu",
                                     icon_custom_emoji_id=e.KNOB_ID,
                                     style=ButtonStyle.DEFAULT),
            ],
        ]
    )


def render_queue_added(title, artist, duration, position: int, eta: str,
                       requested_by) -> str:
    """Caption for the 'Added to Queue' card. Premium custom emoji (verified
    IDs only, via bot.utils.emoji) with unicode fallbacks. All dynamic values
    escaped."""
    lines = [
        f"{e.NOTE} <b>Added to Queue</b>",
        "",
        f"{e.MUSIC} <b>{html.escape((title or 'Unknown title').strip())}</b>",
    ]
    if artist:
        lines.append(f"{e.USER} {html.escape(artist.strip())}")
    lines.append(f"{e.CLOCK} {_fmt_dur(duration)}")
    lines += [
        "",
        f"{e.PIN} <b>Position:</b> #{position}",
        f"{e.CLOCK} Plays in {html.escape(eta)}",
        "",
        f"Requested by {html.escape(str(requested_by or 'someone'))}",
    ]
    return "\n".join(lines)


def queue_added_keyboard(position: int, styled: bool = True) -> InlineKeyboardMarkup:
    """[Skip] [Change] [Queue] for the queue-added card.

    Skip reuses the existing mp:skip control; Change carries this track's
    queue position; Queue opens a compact queue popup. styled=True uses the
    2026 coloured ButtonStyle; the caller retries styled=False if a send is
    rejected so the controls never disappear."""
    if not styled:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Skip", callback_data="mp:skip")],
            [InlineKeyboardButton("Change", callback_data=f"mp:chgsong:{position}")],
            [InlineKeyboardButton("Queue", callback_data="mp:queue")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Skip", callback_data="mp:skip",
                              icon_custom_emoji_id=e.BOLT2_ID,
                              style=ButtonStyle.DANGER)],
        [InlineKeyboardButton("Change", callback_data=f"mp:chgsong:{position}",
                              icon_custom_emoji_id=e.DICE_ID,
                              style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton("Queue", callback_data=f"mp:queue",
                              icon_custom_emoji_id=e.INBOX_ID,
                              style=ButtonStyle.SUCCESS)],
    ])
