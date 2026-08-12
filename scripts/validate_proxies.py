#!/usr/bin/env python3
"""Validate a SOCKS5 proxy list against YouTube and rewrite it in place.

Public free proxy lists rot fast. Run this whenever yt-dlp starts
returning "Requested format is not available" across multiple videos
— that almost always means most of the pool has gone dead since the
last validation, not that the bot's logic broke.

Two tiers per proxy:
  1. HTTPS to https://www.youtube.com/generate_204 — short, lightweight,
     returns 204. A SOCKS5 proxy that can't reach this fails.
  2. yt-dlp -F against a known-public video (Rick Astley dQw4w9WgXcQ)
     with no cookies. Survivors must produce real mp4/webm formats —
     storyboards-only counts as a failure (means the IP is already on
     YouTube's PO-token-required list, useless for our purposes).

Survivors of both tiers are written back to the proxies file. Originals
that fail are dropped. Use --dry-run to inspect without rewriting.

Usage:
  python3 scripts/validate_proxies.py [path/to/proxies.txt] [--dry-run]
"""

import concurrent.futures
import re
import shutil
import subprocess
import sys
from pathlib import Path

YT_TEST_VIDEO = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
T1_TIMEOUT_S = 8
T2_TIMEOUT_S = 12
PARALLELISM_T1 = 30
PARALLELISM_T2 = 8
DEFAULT_PATH = Path(__file__).resolve().parent.parent / "proxies.txt"


def tier1(proxy: str) -> bool:
    host = proxy.removeprefix("socks5://")
    try:
        out = subprocess.run(
            [
                "curl", "--silent", "--max-time", str(T1_TIMEOUT_S),
                "--socks5-hostname", host,
                "-o", "/dev/null", "-w", "%{http_code}",
                "https://www.youtube.com/generate_204",
            ],
            capture_output=True, text=True, timeout=T1_TIMEOUT_S + 4,
        )
        return out.stdout.strip() in ("204", "200")
    except Exception:
        return False


def tier2(proxy: str) -> bool:
    try:
        out = subprocess.run(
            [
                "yt-dlp", "--socket-timeout", str(T2_TIMEOUT_S), "--no-warnings",
                "--proxy", proxy, "-F", YT_TEST_VIDEO,
            ],
            capture_output=True, text=True, timeout=T2_TIMEOUT_S + 10,
        )
        return bool(re.search(r"^\d+\s+(mp4|webm)", out.stdout, re.M))
    except Exception:
        return False


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a != "--dry-run"]
    dry_run = "--dry-run" in argv
    path = Path(args[0]) if args else DEFAULT_PATH
    if not path.exists():
        print(f"no such file: {path}", file=sys.stderr)
        return 1

    proxies = [
        ln.strip() for ln in path.read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    print(f"input: {len(proxies)} entries from {path}")

    with concurrent.futures.ThreadPoolExecutor(PARALLELISM_T1) as ex:
        t1_ok = [p for p, ok in zip(proxies, ex.map(tier1, proxies)) if ok]
    print(f"tier 1 (HTTPS to youtube): {len(t1_ok)}/{len(proxies)} pass")

    if not t1_ok:
        print("nothing survived tier 1 — pool is dead.")
        return 2

    with concurrent.futures.ThreadPoolExecutor(PARALLELISM_T2) as ex:
        t2_ok = [p for p, ok in zip(t1_ok, ex.map(tier2, t1_ok)) if ok]
    print(f"tier 2 (yt-dlp real formats): {len(t2_ok)}/{len(t1_ok)} pass")

    if not t2_ok:
        print(
            "every reachable proxy returned storyboards-only or no formats.\n"
            "this source isn't viable — try a paid/residential provider."
        )
        return 3

    if dry_run:
        print("--dry-run set; survivors:")
        print("\n".join(t2_ok))
        return 0

    shutil.copy(path, str(path) + ".bak")
    path.write_text("\n".join(t2_ok) + "\n")
    print(f"rewrote {path} with {len(t2_ok)} survivors (backup at {path}.bak)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
