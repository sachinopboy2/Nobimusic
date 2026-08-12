"""Resso metadata resolver.

Resso doesn't have a public song-streaming API. We fetch the share page and pull
the song title + artist out of the standard OpenGraph / Twitter meta tags, then
hand that string off to the YouTube searcher.
"""

import re

import aiohttp


def is_resso_url(url: str) -> bool:
    return "resso.com" in url


def _meta(html: str, *keys: str) -> str | None:
    for key in keys:
        pattern = (
            rf'<meta\s+(?:property|name)="{re.escape(key)}"\s+content="([^"]+)"'
        )
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


async def resolve_resso(url: str) -> str | None:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13; SM-S908E) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        ),
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, allow_redirects=True) as resp:
            if resp.status != 200:
                return None
            html = await resp.text()

    title = _meta(html, "og:title", "twitter:title")
    description = _meta(html, "og:description", "twitter:description")

    if not title:
        return None
    if description and (" - " in description or " by " in description.lower()):
        return description
    return title
