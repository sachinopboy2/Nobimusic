import logging
import os
import random
from dotenv import load_dotenv
from urllib.parse import urlparse

load_dotenv()

_log = logging.getLogger("WarbornMusic.config")


def _require(name: str) -> str:
    """Fetch a mandatory env var or fail with a clear, actionable message.

    Without this, a missing API_ID surfaces as an opaque
    ``int(None)`` TypeError deep in import — unhelpful for someone who
    just forgot to fill in .env. This points straight at the fix.
    """
    val = os.getenv(name, "").strip()
    if not val:
        raise SystemExit(
            f"[config] Required environment variable {name} is not set. "
            f"Copy .env.example to .env and fill in {name} "
            f"(see the README → Environment Variables)."
        )
    return val


# ─── Required credentials (see .env.example) ─────────────────────────────
API_ID = int(_require("API_ID"))
API_HASH = _require("API_HASH")
BOT_TOKEN = _require("BOT_TOKEN")
STRING_SESSION = _require("STRING_SESSION")

# Optional. Needed only for Spotify links. Get yours at
# https://developer.spotify.com/dashboard (free).
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

# ─── Owner/Sudo ID (comma-separated for multiple owners) ────────────────
_owner_raw = os.getenv("OWNER_ID", "").strip()
try:
    OWNER_ID = int(_owner_raw) if _owner_raw.isdigit() else (
        int(_owner_raw.split(",")[0].strip()) if _owner_raw else 0
    )
except (ValueError, TypeError):
    _log.warning("config: OWNER_ID=%r is not a valid integer — ignoring", _owner_raw)
    OWNER_ID = 0

# Optional external media-downloader microservice. If MEDIA_API_URL is set,
# Instagram and Pinterest downloads call it first (POST {url}/download with
# X-API-Key) and only fall through to the in-process yt-dlp path if the API
# returns no file. Unset = entirely disabled; in-process yt-dlp is the only
# path and behavior is identical to before this integration. YouTube never
# touches the API — its existing cookie/proxy chain stays the only path.
MEDIA_API_URL = os.getenv("MEDIA_API_URL", "").strip().rstrip("/")
MEDIA_API_KEY = os.getenv("MEDIA_API_KEY", "").strip()

# Per-platform kill switch for the media API. If the API host can't reach
# Instagram (datacenter IP returning login_required), set this to false to
# skip the API call for IG and go straight to the local fallback. Pinterest
# is unaffected — only the IG path checks this flag.
MEDIA_API_INSTAGRAM_ENABLED = (
    os.getenv("MEDIA_API_INSTAGRAM_ENABLED", "true").strip().lower()
    in ("1", "true", "yes", "on")
)


def _parse_proxy_url(raw: str) -> dict | None:
    """Parse PROXY_URL into a pyrofork-compatible proxy config.

    Accepts: socks4://, socks5://, http:// URLs, optionally with
    user:pass auth. Returns None on missing/invalid input so callers
    can short-circuit cleanly.

    Example:
      socks5://user:pass@host:1080
      http://host:8080
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        u = urlparse(raw)
    except Exception:
        return None
    scheme = (u.scheme or "").lower()
    if scheme not in ("socks4", "socks5", "http"):
        return None
    if not u.hostname or not u.port:
        return None
    cfg = {"scheme": scheme, "hostname": u.hostname, "port": u.port}
    if u.username:
        cfg["username"] = u.username
    if u.password:
        cfg["password"] = u.password
    return cfg


def _parse_shorthand(line: str) -> dict | None:
    """Parse the host:port:user:pass shorthand used by PureVPN-style proxy
    lists. Returns the same dict shape as `_parse_proxy_url`. Defaults
    scheme to http since that's what those providers ship.
    """
    parts = line.strip().split(":")
    if len(parts) < 2:
        return None
    host = parts[0].strip()
    try:
        port = int(parts[1].strip())
    except (ValueError, IndexError):
        return None
    if not host or not (0 < port < 65536):
        return None
    cfg = {"scheme": "http", "hostname": host, "port": port}
    if len(parts) >= 4:
        u, p = parts[2].strip(), parts[3].strip()
        if u:
            cfg["username"] = u
        if p:
            cfg["password"] = p
    return cfg


def _load_proxies_file(path: str) -> list[dict]:
    """Read a proxy pool file. One proxy per line. Lines may be:
    - a URL: socks5://user:pass@host:port
    - shorthand: host:port:user:pass

    Blank lines and lines starting with # are ignored.
    """
    out: list[dict] = []
    if not path or not os.path.exists(path):
        return out
    try:
        with open(path) as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                cfg = _parse_proxy_url(line) or _parse_shorthand(line)
                if cfg is not None:
                    out.append(cfg)
    except OSError:
        pass
    return out


def _pick_proxy() -> dict | None:
    """Resolve a single proxy config to use for this process.

    Priority:
    1. PROXY_URL — explicit single proxy (URL form).
    2. PROXIES_FILE — pool file; pick a random one per process start so
       restarts spread load and a flaky proxy doesn't permanently break
       the bot.
    """
    single = os.getenv("PROXY_URL", "").strip()
    if single:
        return _parse_proxy_url(single)

    pool_path = os.getenv("PROXIES_FILE", "").strip()
    pool = _load_proxies_file(pool_path)
    if not pool:
        return None
    pick = random.choice(pool)
    _log.info(
        "config: picked proxy %s://%s:%s (pool size %d)",
        pick["scheme"], pick["hostname"], pick["port"], len(pool),
    )
    return pick


# Single source of truth for an outbound proxy. Used by both pyrofork
# clients (bot + userbot) and as the default fallback for YT_DLP_PROXY.
# Leave PROXY_URL/PROXIES_FILE empty for direct connection.
PROXY_URL = os.getenv("PROXY_URL", "").strip()
PROXY = _pick_proxy()


# ─── Branding & public links (all optional, fully configurable) ──────────
# These drive the /start and /help cards, the /stats header, and the
# inline buttons. Nothing here is hardcoded — leave a value blank and the
# matching button/line is simply omitted, so a freshly forked bot works
# out of the box with only the required credentials filled in.

# Display name used across user-facing messages (start/help/stats).
BOT_NAME = os.getenv("BOT_NAME", "Warborn Music").strip() or "Warborn Music"

# Public @username of THIS bot, used to build the "Add me to your group"
# link. If unset, the bot resolves its own username at runtime, so this
# is optional — set it only to override.
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")

# Public links shown as buttons on /start. Accept either a full URL
# (https://t.me/...) or a bare @username / t.me handle — normalized below.
SUPPORT_CHAT = os.getenv("SUPPORT_CHAT", "").strip()
UPDATE_CHANNEL = os.getenv("UPDATE_CHANNEL", "").strip()
OWNER_URL = os.getenv("OWNER_URL", "").strip()

# Optional default log channel/group id. /setlog can still set this at
# runtime; this env var just provides the initial destination so logging
# works immediately after deploy. Comma/space list not supported — one id.
_log_group_raw = os.getenv("LOG_GROUP_ID", "").strip()
try:
    LOG_GROUP_ID = int(_log_group_raw) if _log_group_raw else None
except ValueError:
    _log.warning("config: LOG_GROUP_ID=%r is not a valid integer — ignoring", _log_group_raw)
    LOG_GROUP_ID = None


def normalize_link(value: str) -> str:
    """Turn a bare @handle or t.me path into a full https URL.

    Accepts and passes through anything already starting with http(s)://.
    Returns "" for empty input so callers can treat "no link" uniformly.
    """
    v = (value or "").strip()
    if not v:
        return ""
    if v.startswith(("http://", "https://")):
        return v
    if v.startswith("@"):
        return f"https://t.me/{v[1:]}"
    if v.startswith("t.me/"):
        return f"https://{v}"
    # Bare handle / invite hash — assume a public username.
    return f"https://t.me/{v}"


# Banner images for /start and /help. Third-party (i.ibb.co) placeholders;
# override with your own image URLs.
START_IMAGE = os.getenv(
    "START_IMAGE", "https://files.catbox.moe/eahc05.jpg"
).strip()
HELP_IMAGE = os.getenv(
    "HELP_IMAGE", "https://files.catbox.moe/eahc05.jpg"
).strip()
