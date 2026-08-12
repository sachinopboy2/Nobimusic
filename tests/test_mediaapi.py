"""Media-API (/download) client + resolver wiring (network mocked).

Covers the the configured API's /download contract: GET /download?url=&type=&api_key= returns
a directly-streamable media URL. Song selection is YouTube's (InnerTube); the
API only fetches the chosen URL, so no wrong song can be substituted.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.utils import mediaapi, resolver

failed = 0


def check(name, ok):
    global failed
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1


def main():
    # 1) download_url builds the right query; api_key placed LAST (log-safe).
    mediaapi.API_URL, mediaapi.API_KEY = "https://api.example.test", "SECRET"
    u = mediaapi.download_url("https://youtu.be/abc", "audio")
    check("download_url has url+type+api_key",
          "url=https" in u and "type=audio" in u and "api_key=SECRET" in u)
    check("api_key is last (redaction-safe)", u.rindex("api_key=") > u.rindex("type="))
    check("_redact hides the key", "SECRET" not in mediaapi._redact(u))

    # 2) enabled() gating
    saved = (mediaapi.API_URL, mediaapi.API_KEY)
    mediaapi.API_KEY = ""
    check("disabled without API_KEY", not mediaapi.enabled())
    mediaapi.API_KEY = "SECRET"
    check("enabled with API_KEY", mediaapi.enabled())

    # 3) fetch_track: preflight True -> streamable url; video/disabled/False -> None
    pf_saved = mediaapi._preflight
    try:
        async def pf_ok(url): return True
        async def pf_no(url): return False
        mediaapi._preflight = pf_ok
        p, t, d = asyncio.run(mediaapi.fetch_track("https://youtu.be/abc"))
        check("fetch_track returns streamable /download url",
              p and p.startswith("https://api.example.test/download?") and "youtu.be" in p)
        check("fetch_track: video is skipped (audio-only here)",
              asyncio.run(mediaapi.fetch_track("https://youtu.be/abc", video=True))[0] is None)
        mediaapi._preflight = pf_no
        check("fetch_track None when preflight fails (bad/unsupported url)",
              asyncio.run(mediaapi.fetch_track("https://youtu.be/abc"))[0] is None)
    finally:
        mediaapi._preflight = pf_saved
        mediaapi.API_URL, mediaapi.API_KEY = saved

    # 4) rate_limited_recently flips after a simulated 429
    mediaapi._last_429 = 0.0
    check("not rate-limited initially", not mediaapi.rate_limited_recently())
    import time as _t
    mediaapi._last_429 = _t.monotonic()
    check("rate-limited right after a 429", mediaapi.rate_limited_recently())
    mediaapi._last_429 = 0.0

    # 5) resolver: YouTube search picks the video, media API fetches THAT url.
    resolver._RESOLVE_CACHE.clear()
    keep = {k: getattr(resolver, k) for k in
            ("search_youtube_detailed", "_api_fetch", "get_audio_meta",
             "get_video_meta", "_via_jiosaavn", "_stream_alive", "_ALLOW_JIOSAAVN")}
    try:
        async def yt_detailed(q, limit=5):
            return [("https://www.youtube.com/watch?v=RIGHT", "Imagine Dragons - Believer")]
        fetched = []
        async def api_ok(url):
            fetched.append(url)
            return ("https://api.example.test/download?url=RIGHT&type=audio&api_key=x", "", None)
        resolver.search_youtube_detailed = yt_detailed
        resolver._api_fetch = api_ok
        p, t, d = asyncio.run(resolver._via_youtube_search("believer"))
        check("audio: YouTube picks video, media API fetches it",
              p == "https://api.example.test/download?url=RIGHT&type=audio&api_key=x")
        check("media API fetched the YouTube URL InnerTube chose",
              fetched == ["https://www.youtube.com/watch?v=RIGHT"])
        check("title comes from YouTube search (correct song)",
              t == "Imagine Dragons - Believer")

        # 6) API miss -> yt-dlp direct extraction fallback
        async def api_miss(url): return (None, "", None)
        async def alive(u): return True
        resolver._api_fetch = api_miss
        resolver._stream_alive = alive
        resolver.get_audio_meta = lambda u: ("http://gv/stream", "yt title", 200)
        async def saavn_no(q): return (None, "", None)
        resolver._via_jiosaavn = saavn_no
        p2, _, _ = asyncio.run(resolver._via_youtube_search("believer"))
        check("API miss falls back to yt-dlp extraction", p2 == "http://gv/stream")

        # 7) YouTube-only by default: API rate-limited, yt-dlp fails -> NO wrong
        #    song (JioSaavn off), and a quota message is returned.
        resolver._ALLOW_JIOSAAVN = False
        resolver.get_audio_meta = lambda u: (None, None, None)
        jio_called = []
        async def jio(q): jio_called.append(q); return ("http://saavn/wrong.mp3", "Wrong", 1)
        resolver._via_jiosaavn = jio
        mediaapi._last_429 = _t.monotonic()  # API reports rate-limited
        out = asyncio.run(resolver._via_youtube_search("believer"))
        check("no wrong-song substitute by default", out[0] is None and not jio_called)
        check("quota message surfaced", "daily limit" in out[1].lower())
        mediaapi._last_429 = 0.0

        # 8) video path never uses the media API (audio-only) -> yt-dlp
        vid_calls = []
        async def api_should_not_run(url):
            vid_calls.append(url); return ("x", "", None)
        resolver._api_fetch = api_should_not_run
        resolver.get_video_meta = lambda u: ("http://gv/video", "vid", 300)
        pv, _, _ = asyncio.run(resolver._via_youtube_search("believer", video=True))
        check("video uses yt-dlp, not the media API", pv == "http://gv/video" and not vid_calls)
    finally:
        for k, v in keep.items():
            setattr(resolver, k, v)
        resolver._RESOLVE_CACHE.clear()

    print(f"\n{'FAILED' if failed else 'OK'}: {failed} failure(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
