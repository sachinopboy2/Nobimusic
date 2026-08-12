"""player.youtube_cookiefile must hand every yt-dlp instance its OWN private
cookie copy.

yt-dlp opens cookiefile read-write and truncates+rewrites it on close, and
resolves run concurrently under asyncio.to_thread — so a SHARED copy lets one
instance truncate the file while another loads it, raising
CookieLoadError("... does not look like a Netscape format cookies file")
(not an ExtractorError/DownloadError, so silently swallowed and misreported as
a bot-wall). Every call must therefore return a distinct, private tempfile.
"""
import os
import sys
import threading

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.utils import player

failed = 0


def check(name, ok):
    global failed
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1


def main():
    import tempfile
    tmp = tempfile.mkdtemp(prefix="ytwork_test_")
    master = os.path.join(tmp, "master_cookies.txt")
    with open(master, "w") as f:
        f.write("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tX\t1\n")
    player.active_youtube_cookies = lambda: master  # bypass cookie_manager

    # 1) returns a real, existing file whose content matches the master
    p = player.youtube_cookiefile()
    check("returns an existing file", bool(p) and os.path.exists(p))
    check("copy content matches master", open(p).read() == open(master).read())
    check("copy is not the master path", p != master)

    # 2) each call returns a DISTINCT private copy (never shared)
    a, b = player.youtube_cookiefile(), player.youtube_cookiefile()
    check("sequential calls return distinct copies", a != b and os.path.exists(a) and os.path.exists(b))

    # 3) concurrent calls each get their OWN path — no shared file to race on
    results, barrier, lock = [], threading.Barrier(8), threading.Lock()

    def worker():
        barrier.wait()
        r = player.youtube_cookiefile()
        with lock:
            results.append(r)

    ts = [threading.Thread(target=worker) for _ in range(8)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    check("concurrent calls all get distinct copies",
          len(set(results)) == len(results) and all(os.path.exists(r) for r in results))

    # 4) an earlier caller's copy is never retired out from under it
    first = player.youtube_cookiefile()
    for _ in range(5):
        player.youtube_cookiefile()
    check("earlier copy still exists after later calls", os.path.exists(first))

    # 5) no jar configured -> "" (yt-dlp runs cookieless)
    player.active_youtube_cookies = lambda: ""
    check("no jar -> empty string", player.youtube_cookiefile() == "")

    # 6) the removed caching API is gone (guards against reintroduction)
    check("reset_youtube_working_copy removed", not hasattr(player, "reset_youtube_working_copy"))

    # 7) _drop_cookie_tempfile removes our copies but NEVER the master
    player.active_youtube_cookies = lambda: master
    c = player.youtube_cookiefile()
    player._drop_cookie_tempfile(c)
    check("drop removes our per-request copy", not os.path.exists(c))
    player._drop_cookie_tempfile(master)  # master isn't tracked -> must be left alone
    check("drop never deletes the master jar", os.path.exists(master))

    print(f"\n{'FAILED' if failed else 'OK'}: {failed} failure(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
