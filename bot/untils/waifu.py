"""Self-contained state + rendering for the /waifu command.

Completely isolated from the rest of the bot: its own persistence namespace
(``waifu.json`` + the ``waifu`` Redis key) and its own in-memory cache. Nothing
here touches any other command, table, cache or handler.

Persistence mirrors the project's standard pattern (see bot.utils.chats):
- in-memory dict serves all reads,
- an atomic local JSON file survives restarts,
- MongoDB (primary) survives redeploys; JSON is fallback.
"""

import html
import json
import os
import random
import time
from threading import Lock

from bot.utils import db
from bot.utils import emoji as e

BOND_SECONDS = 86_400  # 24h, strictly elapsed time
WAIFU_FILE = os.getenv("WAIFU_FILE", "waifu.json")
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "waifu")
# Premium default images used when the waifu's Telegram profile photo can't be
# fetched. WAIFU_FALLBACK_IMAGE overrides with a single custom image.
_FALLBACK_IMAGES = [os.path.join(_ASSETS, "fallback_1.jpg"),
                    os.path.join(_ASSETS, "fallback_2.jpg")]


def fallback_image() -> str:
    """A premium default image for when the profile photo is unavailable — the
    operator override if set, else a randomly chosen bundled fallback."""
    return os.getenv("WAIFU_FALLBACK_IMAGE") or random.choice(_FALLBACK_IMAGES)

# Optional card heading. Empty by default (no brand line). Set WAIFU_BRAND to
# add your own title, e.g. "🌸 My Music Bot".
BRAND = os.getenv("WAIFU_BRAND", "").strip()

CHEMISTRY = ["★☆☆☆☆", "★★☆☆☆", "★★★☆☆", "★★★★☆", "★★★★★"]
RELATIONSHIPS = [
    "Soulmates", "Lovers", "Married", "Crush", "Best Match", "Destined",
    "Perfect Pair", "Secret Admirer", "Heart Stealer", "Eternal Bond",
]
QUOTES = [
    "Fate made today's choice.",
    "A beautiful encounter begins.",
    "Destiny has spoken.",
    "A perfect match... maybe.",
    "The stars seem to agree.",
    "Today's heart belongs here.",
    "Love found a direction.",
    "An unexpected connection.",
    "Some meetings are written in the stars.",
    "A little luck, a little destiny.",
    "Love works in mysterious ways.",
    "Every legend starts with a meeting.",
    "Hearts don't always choose logically.",
    "Some people are worth finding.",
    "This pairing wasn't an accident.",
]
LAYOUT_IDS = list(range(1, 9))  # eight premium layouts

# ── persistence ──────────────────────────────────────────────────────────
_lock = Lock()
_loaded = False
_profiles: dict[str, dict] = {}


def _load() -> None:
    global _loaded
    if _loaded:
        return

    local: dict[str, dict] = {}
    if os.path.exists(WAIFU_FILE):
        try:
            with open(WAIFU_FILE) as f:
                data = json.load(f)
            if isinstance(data, dict):
                local = data
        except (OSError, ValueError, TypeError):
            pass
    _profiles.update(local)

    # 1. MongoDB (primary — persistent)
    if db.ready():
        if not _loaded:
            try:
                remote = db.load_waifus()
                if isinstance(remote, dict):
                    _profiles.update(remote)  # Mongo authoritative
                if _profiles and (not isinstance(remote, dict) or len(remote) < len(_profiles)):
                    db.save_waifus(_profiles)  # migrate local into Mongo once
                _loaded = True
            except Exception:
                pass
        if _loaded:
            return

    _loaded = True


def _save() -> None:
    # 1. MongoDB (primary)
    if db.ready():
        try:
            db.save_waifus(_profiles)
        except Exception:
            pass

    # 2. Local JSON backup
    tmp = WAIFU_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(_profiles, f)
        os.replace(tmp, WAIFU_FILE)
    except OSError:
        pass


def _key(user_id: int, chat_id: int) -> str:
    """Per-user, per-group storage key so a bond in one group is never returned
    in another (privacy) — each group keeps an independent waifu + 24h cooldown."""
    return f"{chat_id}:{user_id}"


def get_profile(user_id: int, chat_id: int) -> dict | None:
    with _lock:
        _load()
        return _profiles.get(_key(user_id, chat_id))


def put_profile(user_id: int, chat_id: int, profile: dict) -> None:
    with _lock:
        _load()
        _profiles[_key(user_id, chat_id)] = profile
        _save()


# ── pure logic ───────────────────────────────────────────────────────────
def is_active(profile: dict, now: float) -> bool:
    """True while the 24h bond is still running (strictly elapsed time)."""
    try:
        return (now - float(profile["assigned_at"])) < BOND_SECONDS
    except (KeyError, TypeError, ValueError):
        return False


def is_eligible(user) -> bool:
    """A real, selectable member: not the bot itself, not a deleted account."""
    return bool(
        user
        and not getattr(user, "is_bot", False)
        and not getattr(user, "is_deleted", False)
        and getattr(user, "id", None)
    )


def new_profile_values() -> dict:
    """The randomly generated values frozen for the whole bond."""
    return {
        "layout": random.choice(LAYOUT_IDS),
        "bond": random.randint(1, 100),
        "chemistry": random.choice(CHEMISTRY),
        "relationship": random.choice(RELATIONSHIPS),
        "quote": random.choice(QUOTES),
    }


def mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={int(user_id)}">{html.escape(name or "Unknown")}</a>'


def _bar(bond: int, cells: int, filled: str, empty: str) -> str:
    n = max(0, min(cells, round(bond / 100 * cells)))
    return filled * n + empty * (cells - n)


# Each builder receives the resolved context and returns the card body. Only
# layouts 1 and 5 show the @username line, which is omitted entirely when the
# waifu has no username (never left as an empty gap).
def _layouts(user: str, username: str | None, bond: int, chemistry: str,
             relationship: str, quote: str) -> dict[int, str]:
    uname = f"\n{e.IDCARD} @{html.escape(username)}" if username else ""
    brand = f"{BRAND}\n" if BRAND else ""
    bar8 = _bar(bond, 8, "▰", "▱")
    bar10 = _bar(bond, 10, "█", "░")
    return {
        1: (
            "╭───────────── ♡ ─────────────╮\n"
            f"{brand}"
            f"      {e.SPARKLE} Today's Waifu {e.SPARKLE}\n"
            f"{e.USER} {user}{uname}\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{e.HEART} Bond  {bar8} {bond}%\n"
            f"{e.DICE} Chemistry  {chemistry}\n"
            f"{e.CROWN} Status  {relationship}\n"
            f'{e.CHAT} "{quote}"\n'
            "╰─────────────────────────────╯"
        ),
        2: (
            "┌──────────────────────────┐\n"
            f"{brand}"
            f"     {e.HEART} Today's Waifu\n"
            f"{e.USER} {user}\n"
            f"{e.HEART} Bond  {bond}%\n"
            f"{e.SPARKLE} Chemistry  {chemistry}\n"
            f"{e.CROWN} Status  {relationship}\n"
            f'"{quote}"\n'
            "└──────────────────────────┘"
        ),
        3: (
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"{brand}"
            f"{e.SPARKLE} Today's Waifu {e.SPARKLE}\n"
            f"{e.USER} {user}\n"
            f"{e.HEART} Bond  {bar10} {bond}%\n"
            f"{e.SPARKLE} Chemistry  {chemistry}\n"
            f"{e.CROWN} Status  {relationship}\n"
            f'{e.CHAT} "{quote}"\n'
            "━━━━━━━━━━━━━━━━━━━━"
        ),
        4: (
            "╭──────────────────────╮\n"
            f"{brand}"
            "      Today's Waifu\n"
            "╰──────────────────────╯\n"
            f"{e.USER} {user}\n"
            f"{e.HEART} Bond  {bond}%\n"
            f"{e.SPARKLE} Affection  {chemistry}\n"
            f"{e.CROWN} Destiny  {relationship}\n"
            f'{e.CHAT} "{quote}"'
        ),
        5: (
            "╔══════════════════════╗\n"
            f"{brand}"
            f"{e.HEART} Today's Waifu\n"
            f"{e.USER} {user}{uname}\n"
            "━━━━━━━━━━━━━━\n"
            f"{e.HEART} Bond  {bond}%\n"
            f"{e.ROSE1} Match  {chemistry}\n"
            f"{e.CROWN} {relationship}\n"
            f'{e.CHAT} "{quote}"\n'
            "╚══════════════════════╝"
        ),
        6: (
            "╭────────────────────────╮\n"
            f"{brand}"
            f"{e.HEART} WAIFU MATCH {e.HEART}\n"
            f"{e.USER} {user}\n"
            f"{e.HEART} Compatibility  {bar10} {bond}%\n"
            f"{e.SPARKLE} Relationship  {relationship}\n"
            f"{e.DICE} Chemistry  {chemistry}\n"
            f'{e.CHAT} "{quote}"\n'
            "╰────────────────────────╯"
        ),
        7: (
            "┏━━━━━━━━━━━━━━━━━━━━┓\n"
            f"{brand}"
            f"{e.SPARKLE} Today's Waifu {e.SPARKLE}\n"
            f"{e.USER} {user}\n"
            f"{e.HEART} Bond  {bond}%\n"
            f"{e.DICE} Chemistry  {chemistry}\n"
            f"{e.CROWN} Status  {relationship}\n"
            f'{e.CHAT} "{quote}"\n'
            "┗━━━━━━━━━━━━━━━━━━━━┛"
        ),
        8: (
            f"╭────── {e.ROSE1} ──────╮\n"
            "   Today's Waifu\n"
            f"{e.USER} {user}\n"
            f"{e.HEART} {bond}%  {e.SPARKLE} {chemistry}\n"
            f"{e.CROWN} {relationship}\n"
            f'{e.CHAT} "{quote}"\n'
            "╰────────────────╯"
        ),
    }


def render_card(profile: dict) -> str:
    """Render the stored profile with its frozen layout + values."""
    user = mention(profile["waifu_id"], profile.get("waifu_name"))
    layout = profile.get("layout", 1)
    cards = _layouts(
        user, profile.get("waifu_username"), int(profile.get("bond", 0)),
        profile.get("chemistry", ""), profile.get("relationship", ""),
        profile.get("quote", ""),
    )
    return cards.get(layout, cards[1])


def owner_header(mention: str) -> str:
    """Prominent top line naming who this waifu is claimed by. Shown on every
    response (first claim and active-lock repeat) so it's always clear whose
    waifu it is. `mention` is a clickable HTML mention of the command sender."""
    return f"{e.CROWN} <b>{mention}'s Waifu</b>\n"


def footer_new() -> str:
    return (
        "\n━━━━━━━━━━━━━━\n"
        f"{e.SPARKLE} Fate has made today's choice.\n"
        f"May this bond bring a little luck and a lot of smiles. {e.HEART}\n"
        "━━━━━━━━━━━━━━"
    )
