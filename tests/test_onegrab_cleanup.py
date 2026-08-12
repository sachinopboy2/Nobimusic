"""Regression: the /refresh play-cache purge must never delete a QUEUED (not
yet played) local file, only true orphans.

Historical note: this used to also cover the OneGrab `_download_tme` flow that
downloaded a t.me file into the reaped play-cache dir. That module was renamed
`onegrab` -> `mediaapi` and its download path was replaced by a direct-stream
`/download` contract (pass 65), so `mediaapi` no longer writes local files —
there is nothing to reap from it. The purge/queue interaction below still
matters for the proxy-download and /song //video local files, so it stays.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.utils import playback
from bot.utils import queue as q

failed = 0


def check(name, ok):
    global failed
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1


def main():
    cache = playback._PLAY_CACHE_DIR

    # active_sources() must include QUEUED tracks, not just the current one,
    # so the purge below can tell a queued file apart from a true orphan.
    q.clear(999)
    os.makedirs(cache, exist_ok=True)
    queued = os.path.join(cache, "queued.m4a")
    orphan = os.path.join(cache, "orphan.m4a")
    open(queued, "wb").close()
    open(orphan, "wb").close()
    q.enqueue(999, q.Track(stream_url=queued, title="q", requested_by="t"))
    check("active_sources() includes queued file", queued in q.active_sources())

    # purge_orphan_media keeps the queued file, deletes the true orphan
    playback.purge_orphan_media()
    check("purge KEEPS queued (not-yet-played) file", os.path.exists(queued))
    check("purge REMOVES true orphan", not os.path.exists(orphan))

    q.clear(999)
    for p in (queued, orphan):
        if os.path.exists(p):
            os.remove(p)

    print(f"\n{'FAILED' if failed else 'OK'}: {failed} failure(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
