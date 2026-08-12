"""MP4/video player UI: clean dynamic titles + default artwork fallback.

Covers:
  • queue.display_title — generic local MP4s render "Mp4 Video[ N]" (numbered
    dynamically from the queue), while real titles (YouTube/Spotify/audio and
    resolved video) are returned untouched.
  • np_ui.render_for_chat — the Now Playing card shows the resolved display
    title.
  • thumbnail — the bundled default artwork is used when a video has no
    thumbnail, and the template-only path still works otherwise.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pyrogram.enums import ChatType

from bot.utils import np_ui
from bot.utils import queue as q
from bot.utils import thumbnail

failed = 0
CHAT = -100424242


def check(name, ok):
    global failed
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1


def _mp4(path):
    return q.Track(stream_url=path, title="Mp4 Video", requested_by="u",
                   is_video=True, generic_mp4=True)


def main():
    # ---- Track model: new flag defaults off (existing constructions unaffected)
    plain = q.Track(stream_url="x", title="Song", requested_by="u")
    check("Track.generic_mp4 defaults to False", plain.generic_mp4 is False)

    # ---- display_title: single generic MP4 -> "Mp4 Video" (no number)
    q.clear(CHAT)
    a = _mp4("/tmp/a.mp4")
    q.set_current(CHAT, a)
    check("single MP4 -> 'Mp4 Video'", q.display_title(CHAT, a) == "Mp4 Video")

    # ---- multiple MP4s -> numbered by queue order; real titles skipped/untouched
    b = _mp4("/tmp/b.mp4")
    yt = q.Track(stream_url="http://yt", title="Imagine Dragons - Believer",
                 requested_by="u", is_video=True)  # resolved video: NOT generic
    c = _mp4("/tmp/c.mp4")
    q.enqueue(CHAT, b)
    q.enqueue(CHAT, yt)
    q.enqueue(CHAT, c)
    check("MP4 #1 (now playing) -> 'Mp4 Video 1'", q.display_title(CHAT, a) == "Mp4 Video 1")
    check("MP4 #2 -> 'Mp4 Video 2'", q.display_title(CHAT, b) == "Mp4 Video 2")
    check("MP4 #3 -> 'Mp4 Video 3'", q.display_title(CHAT, c) == "Mp4 Video 3")
    check("resolved video title untouched", q.display_title(CHAT, yt) == "Imagine Dragons - Believer")

    # ---- audio / real titles never rewritten
    audio = q.Track(stream_url="http://a", title="Some Artist - Track", requested_by="u")
    check("audio title untouched", q.display_title(CHAT, audio) == "Some Artist - Track")

    # ---- numbering is dynamic: removing MP4 #1 renumbers the rest by queue order
    q.pop_next(CHAT)  # a -> history, current becomes b
    check("after advance, old #2 becomes #1", q.display_title(CHAT, b) == "Mp4 Video 1")
    check("after advance, old #3 becomes #2", q.display_title(CHAT, c) == "Mp4 Video 2")

    # ---- a generic track not in the timeline still renders clean (no filename)
    orphan = _mp4("/tmp/orphan.mp4")
    check("orphan generic MP4 -> clean 'Mp4 Video'", q.display_title(CHAT, orphan) == "Mp4 Video")

    # ---- Now Playing card shows the resolved display title, not a filename
    q.clear(CHAT)
    m1 = _mp4("/tmp/AQM3SzYo8Gcx_hash.mp4")
    m2 = _mp4("/tmp/other_hash.mp4")
    q.set_current(CHAT, m1)
    q.enqueue(CHAT, m2)
    card = np_ui.render_for_chat(CHAT, m1)
    check("Now Playing card shows 'Mp4 Video 1'", "Mp4 Video 1" in card)
    check("Now Playing card never leaks the filename/hash", "AQM3SzYo8Gcx" not in card)
    q.clear(CHAT)

    # ---- default artwork asset is bundled and used for thumbnail-less video
    check("bundled default artwork exists on disk", os.path.isfile(thumbnail._DEFAULT_ART_PATH))
    check("default artwork loads to bytes", thumbnail._load_default_art() is not None)

    loop = asyncio.new_event_loop()
    try:
        png_default = loop.run_until_complete(thumbnail.generate(None, default_when_missing=True))
        png_plain = loop.run_until_complete(thumbnail.generate(None, default_when_missing=False))
    finally:
        loop.close()
    check("video-with-no-thumb -> composited PNG produced",
          png_default is not None and png_default.read(4) == b"\x89PNG")
    check("audio-with-no-thumb still renders (template-only path intact)",
          png_plain is not None)

    # ---- default_photo() returns the RAW /vplay banner (a JPEG), not a card
    check("bundled /vplay banner exists on disk", os.path.isfile(thumbnail._VPLAY_IMAGE_PATH))
    ph = thumbnail.default_photo()
    check("default_photo() returns a fresh BytesIO", ph is not None and hasattr(ph, "read"))
    raw = ph.read()
    with open(thumbnail._VPLAY_IMAGE_PATH, "rb") as f:
        banner = f.read()
    check("default_photo() bytes == the /vplay banner (raw, not composited)", raw == banner)
    check("default_photo() is a JPEG (the supplied image)", raw[:3] == b"\xff\xd8\xff")
    # the /vplay banner is its own asset, independent of the composited fallback
    with open(thumbnail._DEFAULT_ART_PATH, "rb") as f:
        composited_fallback = f.read()
    check("/vplay banner is a separate asset from the composited fallback",
          banner != composited_fallback)

    # ---- /vplay attaches THIS image; /play keeps the composited card
    from bot.utils import play_actions as pa

    saved = (pa.thumbnail.default_photo, pa.thumbnail.generate, pa._track_artwork)
    sent = {}

    class _Cli:
        async def send_photo(self, chat_id, photo, **kw):
            sent["photo"] = photo

        async def send_message(self, *a, **k):
            sent["photo"] = "TEXT_FALLBACK"

    async def _fake_generate(url, **kw):
        return "COMPOSITED_CARD"

    async def _fake_art(_t):
        return None

    pa.thumbnail.default_photo = lambda: "RAW_VIDEO_IMAGE"
    pa.thumbnail.generate = _fake_generate
    pa._track_artwork = _fake_art
    loop2 = asyncio.new_event_loop()
    try:
        vid = q.Track(stream_url="/tmp/x.mp4", title="Mp4 Video",
                      requested_by="u", is_video=True, generic_mp4=True)
        sent.clear()
        loop2.run_until_complete(pa._send_now_playing(_Cli(), CHAT, vid))
        check("/vplay attaches the dedicated video image", sent.get("photo") == "RAW_VIDEO_IMAGE")

        aud = q.Track(stream_url="http://a", title="Some Song", requested_by="u")
        sent.clear()
        loop2.run_until_complete(pa._send_now_playing(_Cli(), CHAT, aud))
        check("/play still uses the composited card", sent.get("photo") == "COMPOSITED_CARD")
    finally:
        loop2.close()
        pa.thumbnail.default_photo, pa.thumbnail.generate, pa._track_artwork = saved

    # ---- Added-to-Queue card: video uses the banner, audio uses the card
    class _Status:
        async def edit_text(self, *a, **k):
            pass

    class _Reply:
        def __init__(self, kind):  # kind: "video" or "audio"
            media = SimpleNamespace(file_unique_id="uid", duration=12,
                                    file_name="AQM3SzYo8Gcx_hash.mp4", title=None)
            setattr(self, kind, media)
            for other in ("video", "video_note", "audio", "voice"):
                if not hasattr(self, other):
                    setattr(self, other, None)
            self.document = None

        async def download(self, file_name=None):
            return "/tmp/warborn_downloads/uid_file"

    class _Msg:
        def __init__(self, reply):
            self.chat = SimpleNamespace(id=CHAT, type=ChatType.SUPERGROUP)
            self.from_user = SimpleNamespace(id=1, first_name="U", username=None)
            self.command = ["vplay"]
            self.reply_to_message = reply

        async def reply_text(self, *a, **k):
            return _Status()

    captured = {}

    async def _cap_queue_card(client, message, status, caption, position, thumb):
        captured["thumb"] = thumb

    async def _noop_log(*a, **k):
        pass

    saved2 = (pa._send_queue_card, pa._log_play, pa.thumbnail.default_photo,
              pa.thumbnail.generate, pa._track_artwork)
    pa._send_queue_card = _cap_queue_card
    pa._log_play = _noop_log
    pa.thumbnail.default_photo = lambda: "BANNER"

    async def _gen(url, **kw):
        return "CARD"

    async def _art(_t):
        return None

    pa.thumbnail.generate = _gen
    pa._track_artwork = _art
    loop3 = asyncio.new_event_loop()
    try:
        # make the chat "active" so do_play takes the enqueue branch
        q.clear(CHAT)
        q.set_current(CHAT, q.Track(stream_url="x", title="playing", requested_by="u"))

        captured.clear()
        loop3.run_until_complete(pa.do_play(object(), _Msg(_Reply("video")), is_video=True))
        check("queued MP4 card uses the /vplay banner", captured.get("thumb") == "BANNER")

        captured.clear()
        loop3.run_until_complete(pa.do_play(object(), _Msg(_Reply("audio")), is_video=False))
        check("queued audio card still uses the composited card", captured.get("thumb") == "CARD")
    finally:
        loop3.close()
        (pa._send_queue_card, pa._log_play, pa.thumbnail.default_photo,
         pa.thumbnail.generate, pa._track_artwork) = saved2
        q.clear(CHAT)

    print(f"\n{'FAILED' if failed else 'OK'}: {failed} failure(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
