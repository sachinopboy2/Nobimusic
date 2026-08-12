"""Spotify metadata resolver.

Spotify doesn't expose audio streams to non-premium API consumers, so we just
pull the track's artist + title and let the YouTube searcher take it from there.

Required env vars (put them in .env):
    SPOTIFY_CLIENT_ID
    SPOTIFY_CLIENT_SECRET

Get them at https://developer.spotify.com/dashboard (free).
"""

import base64
import os
import re
import time

import aiohttp

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

_TRACK_RE = re.compile(r"spotify\.com/(?:intl-[a-z]+/)?track/([A-Za-z0-9]+)")
_token_cache = {"value": None, "expires_at": 0.0}


def is_spotify_url(url: str) -> bool:
    return "open.spotify.com" in url or "spotify.com" in url


async def _get_token() -> str | None:
    if _token_cache["value"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["value"]
    if not SPOTIFY_CLIENT_ID or not SPOTIFY_CLIENT_SECRET:
        return None

    auth = base64.b64encode(
        f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode()
    ).decode()
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://accounts.spotify.com/api/token",
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data="grant_type=client_credentials",
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

    token = data.get("access_token")
    if not token:
        return None
    _token_cache["value"] = token
    _token_cache["expires_at"] = time.time() + float(data.get("expires_in", 3600)) - 60
    return token


async def resolve_spotify(url: str) -> str | None:
    """Return a 'Artist - Title' string for a Spotify track URL, or None on failure."""
    match = _TRACK_RE.search(url)
    if not match:
        return None
    track_id = match.group(1)

    token = await _get_token()
    if not token:
        return None

    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"https://api.spotify.com/v1/tracks/{track_id}",
            headers={"Authorization": f"Bearer {token}"},
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()

    title = data.get("name", "")
    artists = ", ".join(artist["name"] for artist in data.get("artists", []) if artist.get("name"))
    query = f"{artists} - {title}".strip(" -")
    return query or None
