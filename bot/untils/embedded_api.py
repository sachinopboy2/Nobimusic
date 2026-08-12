"""Embedded Media API server — self-hosted yt-dlp download service.

Spins up automatically when all external Media API endpoints are down.
Runs inside the bot process on a random available port, generates its
own API key, and registers itself in the endpoint registry so the
existing media_api_client uses it seamlessly.

Uses aiohttp.web (already a dependency) — no extra packages needed.
Implements the same /health and /download contract as the external
ytdlp-api-clean service the operator deployed previously.
"""

import asyncio
import logging
import os
import secrets
import shutil
import socket
import tempfile
from typing import Optional

from aiohttp import web

logger = logging.getLogger("WarbornMusic.embedded_api")

_server: Optional["EmbeddedApiServer"] = None
_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv")
_PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")
_IG_MOBILE_UA = (
    "Instagram 344.0.0.0.0 Android (33/13; 420dpi; 1080x2400; "
    "samsung; SM-S918B; dm3q; qcom; en_US; 605596538)"
)


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _classify_error(text: str) -> tuple[str, bool]:
    low = text.lower()
    if any(k in low for k in ("sign in", "log in", "login required", "empty media response")):
        return "LOGIN_REQUIRED", False
    if "private" in low:
        return "PRIVATE_ACCOUNT", False
    if any(k in low for k in ("not available", "removed", "does not exist", "404")):
        return "MEDIA_NOT_FOUND", False
    if any(k in low for k in ("429", "too many requests", "rate limit")):
        return "RATE_LIMITED", True
    if any(k in low for k in ("unsupported url", "no extractor")):
        return "UNSUPPORTED_URL", False
    if any(k in low for k in ("geo-restricted", "not available in your country")):
        return "GEO_BLOCKED", False
    return "EXTRACTION_FAILED", False


def _download_sync(url: str, out_dir: str) -> dict:
    from yt_dlp import YoutubeDL
    from bot.utils.player import cookies_for_url

    captured_errors = []

    class _Logger:
        def debug(self, msg): pass
        def info(self, msg): pass
        def warning(self, msg): pass
        def error(self, msg):
            captured_errors.append(msg)
            logger.warning("embedded_api[yt-dlp]: %s", msg[:200])

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "http_headers": {"User-Agent": _IG_MOBILE_UA},
        "socket_timeout": 20,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 16,
        "http_chunk_size": 5 * 1024 * 1024,
        "format": "bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        "age_limit": 100,
        "noplaylist": False,
        "ignoreerrors": True,
        "logger": _Logger(),
    }

    ck = cookies_for_url(url)
    if ck:
        opts["cookiefile"] = ck

    try:
        with YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as exc:
        code, retryable = _classify_error(str(exc))
        return {"ok": False, "error": {"code": code, "message": str(exc)[:300]},
                "retryable": retryable}

    files = []
    for name in sorted(os.listdir(out_dir)):
        low = name.lower()
        if low.endswith(_VIDEO_EXTS) or low.endswith(_PHOTO_EXTS):
            files.append(os.path.join(out_dir, name))

    if files:
        return {"ok": True, "files": files}

    reason = "unknown"
    for err in captured_errors:
        code, _ = _classify_error(err)
        if code != "EXTRACTION_FAILED":
            reason = code
            break
    return {"ok": False, "error": {"code": reason, "message": captured_errors[0][:300] if captured_errors else "no output"},
            "retryable": False}


class EmbeddedApiServer:
    def __init__(self):
        self.port: int = 0
        self.api_key: str = ""
        self.url: str = ""
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> tuple[str, str]:
        if self._running:
            return self.url, self.api_key

        self.port = _find_free_port()
        self.api_key = secrets.token_hex(32)
        self.url = f"http://127.0.0.1:{self.port}"

        self._app = web.Application()
        self._app["api_key"] = self.api_key
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_post("/download", self._handle_download)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", self.port)
        await site.start()
        self._running = True

        logger.info("embedded_api: started on port %d", self.port)
        return self.url, self.api_key

    async def stop(self):
        if self._runner:
            await self._runner.cleanup()
        self._running = False
        logger.info("embedded_api: stopped")

    def _check_auth(self, request: web.Request) -> bool:
        key = request.headers.get("X-API-Key", "")
        return key == self._app["api_key"]

    async def _handle_health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "provider": "embedded", "port": self.port})

    async def _handle_download(self, request: web.Request) -> web.Response:
        if not self._check_auth(request):
            return web.json_response(
                {"ok": False, "error": {"code": "UNAUTHORIZED", "message": "invalid key"}},
                status=401)

        try:
            body = await request.json()
        except Exception:
            return web.json_response(
                {"ok": False, "error": {"code": "INVALID_REQUEST", "message": "invalid JSON"}},
                status=400)

        url = body.get("url", "").strip()
        if not url:
            return web.json_response(
                {"ok": False, "error": {"code": "INVALID_URL", "message": "missing url"}},
                status=400)

        tmp_dir = tempfile.mkdtemp(prefix="emb_dl_")
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_download_sync, url, tmp_dir),
                timeout=90,
            )
        except asyncio.TimeoutError:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return web.json_response(
                {"ok": False, "error": {"code": "TIMEOUT", "message": "download timed out"}},
                status=504)

        if not result.get("ok"):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            err = result.get("error", {})
            status = 429 if err.get("code") == "RATE_LIMITED" else 422
            return web.json_response({"ok": False, "error": err}, status=status)

        files = result["files"]
        if len(files) == 1:
            return web.FileResponse(files[0], headers={
                "Content-Disposition": f'attachment; filename="{os.path.basename(files[0])}"',
                "X-Cleanup-Dir": tmp_dir,
            })

        import zipfile
        zip_path = os.path.join(tmp_dir, "carousel.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            for f in files:
                zf.write(f, os.path.basename(f))

        return web.FileResponse(zip_path, headers={
            "Content-Type": "application/zip",
            "Content-Disposition": 'attachment; filename="carousel.zip"',
            "X-Cleanup-Dir": tmp_dir,
        })


async def ensure_running() -> tuple[str, str]:
    global _server
    if _server and _server.running:
        return _server.url, _server.api_key
    _server = EmbeddedApiServer()
    return await _server.start()


async def stop_server():
    global _server
    if _server:
        await _server.stop()
        _server = None


def is_running() -> bool:
    return _server is not None and _server.running
