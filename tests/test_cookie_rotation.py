"""Bot-wall cookie failover: /play (_try_extract) and /song,/video
(_try_download) must rotate through EVERY configured jar before giving up, and
the user-facing message must not tell the operator to add cookies they already
have.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from yt_dlp.utils import DownloadError

from bot.utils import player, downloader, resolver

failed = 0


def check(name, ok):
    global failed
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1


_BOT_TEXT = "Sign in to confirm you're not a bot"


def test_play_walks_all_jars():
    """_try_extract should retry _max_cookie_rotations times (one per extra jar)."""
    recovers = {"n": 0}
    JARS = 4  # pretend 4 jars -> 3 rotations
    player.active_youtube_cookies = lambda: "/tmp/fakejar"
    player.proxy_pool_size = lambda: 1
    player.current_proxy = lambda: None
    player.mark_proxy_ok = lambda *a, **k: None
    player.mark_proxy_failed = lambda *a, **k: None
    player.rotate_proxy = lambda *a, **k: None
    player._max_cookie_rotations = lambda: JARS - 1
    player._cookie_recover = lambda: (recovers.__setitem__("n", recovers["n"] + 1) or True)
    player._extract_pass = lambda *a, **k: (None, DownloadError(_BOT_TEXT), 1)  # always bot-wall

    raised = None
    try:
        player._try_extract("https://youtu.be/x", None, video=False)
    except Exception as e:
        raised = e
    check("play: raises YouTubeAuthRequiredError after exhausting jars",
          isinstance(raised, player.YouTubeAuthRequiredError))
    check(f"play: rotated through every jar ({JARS-1} rotations)", recovers["n"] == JARS - 1)


def test_download_walks_all_jars():
    """_try_download should rotate the cookie jar on a bot-wall, once per extra jar."""
    recovers = {"n": 0}
    JARS = 3  # -> 2 rotations
    downloader.active_youtube_cookies = lambda: "/tmp/fakejar"
    downloader.proxy_pool_size = lambda: 1
    downloader.current_proxy = lambda: None
    downloader.mark_proxy_ok = lambda *a, **k: None
    downloader.mark_proxy_failed = lambda *a, **k: None
    downloader.rotate_proxy = lambda *a, **k: None
    downloader._max_cookie_rotations = lambda: JARS - 1
    downloader._cookie_recover = lambda: (recovers.__setitem__("n", recovers["n"] + 1) or True)
    downloader._is_youtube_url = lambda u: True
    downloader._download_pass = lambda *a, **k: (None, None, DownloadError(_BOT_TEXT))

    raised = None
    try:
        downloader._try_download("https://youtu.be/x", video=False)
    except Exception as e:
        raised = e
    check("download: raises after exhausting jars", isinstance(raised, Exception))
    check(f"download: rotated through every jar ({JARS-1} rotations)", recovers["n"] == JARS - 1)


def test_message_is_cookie_aware():
    exc = DownloadError(_BOT_TEXT)
    player.active_youtube_cookies = lambda: "/tmp/fakejar"
    msg_have = resolver._humanize_ytdlp_error(exc)
    check("message (cookies present): no 'add cookies' instruction",
          "Add a Netscape" not in msg_have and "COOKIES_FILE" not in msg_have)
    check("message (cookies present): says rate-limit / refresh",
          "rate-limit" in msg_have.lower() or "refresh" in msg_have.lower())

    player.active_youtube_cookies = lambda: ""
    msg_none = resolver._humanize_ytdlp_error(exc)
    check("message (no cookies): keeps the add-cookies instruction",
          "Add a Netscape" in msg_none)


def test_client_order_and_po_token():
    # Resilient, non-PO-token clients lead the chain (tv/web_safari before web/mweb)
    order = player.PLAYER_CLIENTS
    check("client chain leads with tv", order[0] == "tv")
    check("web_safari present and before web",
          "web_safari" in order and order.index("web_safari") < order.index("web"))
    check("mweb/web are last-resort (after tv)",
          order.index("web") > order.index("tv") and order.index("mweb") > order.index("tv"))

    # PO token opt-in: injected into extractor_args only when configured
    saved = player._PO_TOKENS
    try:
        player._PO_TOKENS = []
        o = player._opts_for("default")
        check("no extractor_args for default client without PO token", "extractor_args" not in o)
        player._PO_TOKENS = ["web.gvs+ABC"]
        o2 = player._opts_for("default")
        check("PO token injected when set",
              o2.get("extractor_args", {}).get("youtube", {}).get("po_token") == ["web.gvs+ABC"])
        o3 = player._opts_for("tv")
        yt = o3["extractor_args"]["youtube"]
        check("client + PO token coexist", yt.get("player_client") == ["tv"] and yt.get("po_token") == ["web.gvs+ABC"])
    finally:
        player._PO_TOKENS = saved


def test_proxy_pool_direct_fallback():
    import os
    os.environ.pop("YT_DLP_PROXY_STRICT", None)
    os.environ["YT_DLP_PROXIES"] = "http://p1@a:1,http://p2@b:2"
    try:
        pool = player._load_proxy_pool()
        check("proxy pool keeps a direct fallback last", pool[-1] == "" and pool[0] and pool[1])
        os.environ["YT_DLP_PROXY_STRICT"] = "1"
        check("YT_DLP_PROXY_STRICT drops the direct fallback", "" not in player._load_proxy_pool())
    finally:
        os.environ.pop("YT_DLP_PROXY_STRICT", None)
        os.environ.pop("YT_DLP_PROXIES", None)


def main():
    test_play_walks_all_jars()
    test_download_walks_all_jars()
    test_message_is_cookie_aware()
    test_client_order_and_po_token()
    test_proxy_pool_direct_fallback()
    print(f"\n{'FAILED' if failed else 'OK'}: {failed} failure(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
