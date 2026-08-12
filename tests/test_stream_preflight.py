"""Resolver stream pre-flight: a googlevideo URL that stalls (CDN throttling)
must be treated as a FAILED resolve so the chain (proxy-download / next result /
JioSaavn) runs, instead of being cached and handed to the player where it dies
with a bare TimeoutError.

Mirrors the current resolver contract (pass 61+): text queries resolve via
YouTube InnerTube search (`search_youtube_detailed`) → media API (`_api_fetch`)
→ yt-dlp extraction → proxy-download local file → JioSaavn (opt-in). Both the
media-API fetch and the JioSaavn fallback are stubbed out here so the tests
exercise the yt-dlp extraction + pre-flight branch deterministically, offline.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.utils import resolver

failed = 0


def check(name, ok):
    global failed
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1


def main():
    # 1) non-googlevideo URLs are never probed (pass through instantly)
    ok = asyncio.run(resolver._stream_alive("https://aac.saavncdn.com/song.mp4"))
    check("non-googlevideo URL passes without probing", ok is True)

    # YouTube InnerTube search returns [(watch_url, title), ...].
    async def fake_search(q):
        return [("https://youtube.com/watch?v=abc", "YT Title")]

    def fake_meta(url):
        return ("https://rr3---sn-x.googlevideo.com/videoplayback?x=1", "YT Title", 200)

    # Media API always misses here so resolution falls through to yt-dlp.
    async def api_miss(url):
        return (None, "", None)

    async def dead(url):  # probe says the CDN stalls
        return False

    async def saavn_hit(q):
        return ("https://aac.saavncdn.com/real.mp4", "Saavn Title", 180)

    async def no_local(url, *, video):  # no proxy configured -> no local download
        return (None, "", None)

    sv = dict(
        search_youtube_detailed=resolver.search_youtube_detailed,
        get_audio_meta=resolver.get_audio_meta,
        get_video_meta=resolver.get_video_meta,
        _stream_alive=resolver._stream_alive,
        _api_fetch=resolver._api_fetch,
        _download_local=resolver._download_local,
        _via_jiosaavn=resolver._via_jiosaavn,
        _ALLOW_JIOSAAVN=resolver._ALLOW_JIOSAAVN,
    )
    try:
        resolver.search_youtube_detailed = fake_search
        resolver.get_audio_meta = fake_meta
        resolver.get_video_meta = fake_meta
        resolver._api_fetch = api_miss
        resolver._stream_alive = dead
        resolver._download_local = no_local
        resolver._via_jiosaavn = saavn_hit

        # 2) dead googlevideo stream + JioSaavn enabled -> falls through to JioSaavn
        resolver._ALLOW_JIOSAAVN = True
        stream, title, dur = asyncio.run(resolver._via_youtube_search("test song"))
        check("dead YT stream skipped -> JioSaavn fallback used",
              stream == "https://aac.saavncdn.com/real.mp4" and title == "Saavn Title")

        # 3) live googlevideo stream -> returned as before (no behaviour change)
        async def alive(url):
            return True
        resolver._stream_alive = alive
        stream2, title2, _ = asyncio.run(resolver._via_youtube_search("test song"))
        check("live YT stream returned as before",
              "googlevideo" in (stream2 or "") and title2 == "YT Title")

        # 4) video + dead stream, no JioSaavn, no proxy download -> clear message
        resolver._stream_alive = dead
        stream3, msg, _ = asyncio.run(resolver._via_youtube_search("test song", video=True))
        check("video dead stream -> None + throttling message",
              stream3 is None and "isn't delivering data" in msg)

        # 5) dead stream + proxy available -> download-through-proxy local file
        #    (audio path parity with the video / direct-link paths)
        async def local_dl(url, *, video):
            return ("/tmp/warborn_downloads/x.m4a", "DL Title", 200)
        resolver._download_local = local_dl
        resolver._stream_alive = dead
        s5, t5, _ = asyncio.run(resolver._via_youtube_search("test song"))
        check("dead stream -> proxy-download local file played",
              s5 == "/tmp/warborn_downloads/x.m4a" and t5 == "DL Title")
    finally:
        for k, v in sv.items():
            setattr(resolver, k, v)

    # 6) resolve() must NOT cache a local-file result (only http URLs)
    resolver._RESOLVE_CACHE.clear()
    async def impl_local(q, *, video=False):
        return ("/tmp/warborn_downloads/y.m4a", "Local", 100)
    _impl = resolver._resolve_impl
    try:
        resolver._resolve_impl = impl_local
        asyncio.run(resolver.resolve("zzz"))
        check("local-file result is not cached", ("zzz", False) not in resolver._RESOLVE_CACHE)
    finally:
        resolver._resolve_impl = _impl
        resolver._RESOLVE_CACHE.clear()

    print(f"\n{'FAILED' if failed else 'OK'}: {failed} failure(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
