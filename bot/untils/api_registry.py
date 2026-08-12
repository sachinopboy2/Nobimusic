"""Encrypted endpoint registry with priority-based failover.

Stores Media API endpoints in a Fernet-encrypted JSON file. Each endpoint
has health state, fail counts, and cooldown timers. The registry picks the
best healthy endpoint and rotates on failure.
"""

import base64
import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("WarbornMusic.api_registry")

_REGISTRY_FILE = os.getenv("API_REGISTRY_FILE", "api_endpoints.enc")
_REGISTRY_SECRET = os.getenv("API_REGISTRY_SECRET", "")

MAX_FAIL_COUNT = 5
COOLDOWN_BASE_S = 60
COOLDOWN_MAX_S = 1800
RESTORE_CHECK_INTERVAL_S = 300


def _derive_key(secret: str) -> bytes:
    if not secret:
        secret = "warborn-music-default-key-change-me"
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


@dataclass
class Endpoint:
    url: str
    api_key: str = ""
    provider: str = "generic"
    priority: int = 100
    healthy: bool = True
    fail_count: int = 0
    last_check: float = 0.0
    last_fail: float = 0.0
    cooldown_until: float = 0.0
    last_success: float = 0.0
    total_requests: int = 0
    total_failures: int = 0

    @property
    def available(self) -> bool:
        return self.healthy and time.time() >= self.cooldown_until

    @property
    def cooldown_remaining(self) -> float:
        return max(0, self.cooldown_until - time.time())


class EndpointRegistry:
    def __init__(self, filepath: str = _REGISTRY_FILE, secret: str = _REGISTRY_SECRET):
        self._filepath = filepath
        self._fernet = Fernet(_derive_key(secret))
        self._endpoints: list[Endpoint] = []
        self._active_idx: int = 0
        self._recovery_log: list[dict] = []

    def load(self) -> bool:
        if not os.path.exists(self._filepath):
            return False
        try:
            with open(self._filepath, "rb") as f:
                encrypted = f.read()
            decrypted = self._fernet.decrypt(encrypted)
            data = json.loads(decrypted)
            self._endpoints = [Endpoint(**ep) for ep in data.get("endpoints", [])]
            self._active_idx = data.get("active_idx", 0)
            if self._active_idx >= len(self._endpoints):
                self._active_idx = 0
            logger.info("api_registry: loaded %d endpoint(s)", len(self._endpoints))
            return True
        except (InvalidToken, json.JSONDecodeError, OSError) as exc:
            logger.warning("api_registry: failed to load %s: %s", self._filepath, exc)
            return False

    def save(self) -> None:
        data = {
            "endpoints": [asdict(ep) for ep in self._endpoints],
            "active_idx": self._active_idx,
        }
        raw = json.dumps(data, indent=2).encode()
        encrypted = self._fernet.encrypt(raw)
        tmp = self._filepath + ".tmp"
        with open(tmp, "wb") as f:
            f.write(encrypted)
        os.replace(tmp, self._filepath)

    def add_endpoint(self, url: str, api_key: str = "", provider: str = "generic",
                     priority: int = 100) -> Endpoint:
        url = url.strip().rstrip("/")
        for ep in self._endpoints:
            if ep.url == url:
                ep.api_key = api_key
                ep.provider = provider
                ep.priority = priority
                self.save()
                return ep
        ep = Endpoint(url=url, api_key=api_key, provider=provider, priority=priority)
        self._endpoints.append(ep)
        self._endpoints.sort(key=lambda e: e.priority)
        self.save()
        logger.info("api_registry: added endpoint %s (provider=%s)", url, provider)
        return ep

    def remove_endpoint(self, url: str) -> bool:
        url = url.strip().rstrip("/")
        before = len(self._endpoints)
        self._endpoints = [ep for ep in self._endpoints if ep.url != url]
        if len(self._endpoints) < before:
            if self._active_idx >= len(self._endpoints):
                self._active_idx = 0
            self.save()
            return True
        return False

    @property
    def endpoints(self) -> list[Endpoint]:
        return list(self._endpoints)

    @property
    def active(self) -> Optional[Endpoint]:
        if not self._endpoints:
            return None
        if self._active_idx < len(self._endpoints):
            ep = self._endpoints[self._active_idx]
            if ep.available:
                return ep
        for i, ep in enumerate(self._endpoints):
            if ep.available:
                self._active_idx = i
                self.save()
                return ep
        return None

    def record_success(self, url: str) -> None:
        for ep in self._endpoints:
            if ep.url == url:
                ep.healthy = True
                ep.fail_count = 0
                ep.last_success = time.time()
                ep.last_check = time.time()
                ep.total_requests += 1
                self.save()
                return

    def record_failure(self, url: str) -> Optional[Endpoint]:
        now = time.time()
        failed_ep = None
        for ep in self._endpoints:
            if ep.url == url:
                failed_ep = ep
                break
        if not failed_ep:
            return None

        failed_ep.fail_count += 1
        failed_ep.last_fail = now
        failed_ep.last_check = now
        failed_ep.total_requests += 1
        failed_ep.total_failures += 1

        if failed_ep.fail_count >= MAX_FAIL_COUNT:
            failed_ep.healthy = False
            backoff = min(COOLDOWN_BASE_S * (2 ** (failed_ep.fail_count - MAX_FAIL_COUNT)),
                          COOLDOWN_MAX_S)
            failed_ep.cooldown_until = now + backoff
            self._log_recovery("endpoint_down", url=url, fail_count=failed_ep.fail_count,
                               cooldown_s=backoff)
            logger.warning("api_registry: %s marked unhealthy (fails=%d, cooldown=%.0fs)",
                           url, failed_ep.fail_count, backoff)

        self.save()
        return self.active

    def restore_endpoint(self, url: str) -> None:
        for i, ep in enumerate(self._endpoints):
            if ep.url == url:
                was_healthy = ep.healthy
                ep.healthy = True
                ep.fail_count = 0
                ep.cooldown_until = 0
                ep.last_check = time.time()
                if not was_healthy:
                    if ep.priority < (self._endpoints[self._active_idx].priority
                                      if self._active_idx < len(self._endpoints) else 999):
                        self._active_idx = i
                    self._log_recovery("endpoint_restored", url=url)
                    logger.info("api_registry: %s restored to healthy", url)
                self.save()
                return

    def get_unhealthy(self) -> list[Endpoint]:
        now = time.time()
        return [ep for ep in self._endpoints
                if not ep.healthy and now >= ep.cooldown_until]

    def get_stale(self, max_age_s: float = RESTORE_CHECK_INTERVAL_S) -> list[Endpoint]:
        now = time.time()
        return [ep for ep in self._endpoints
                if not ep.healthy and (now - ep.last_check) >= max_age_s
                and now >= ep.cooldown_until]

    def _log_recovery(self, action: str, **kwargs) -> None:
        entry = {"action": action, "timestamp": time.time(), **kwargs}
        self._recovery_log.append(entry)
        if len(self._recovery_log) > 200:
            self._recovery_log = self._recovery_log[-100:]

    @property
    def recovery_log(self) -> list[dict]:
        return list(self._recovery_log)

    def seed_from_env(self) -> None:
        from bot.config import MEDIA_API_URL, MEDIA_API_KEY
        if MEDIA_API_URL and not any(ep.url == MEDIA_API_URL for ep in self._endpoints):
            self.add_endpoint(url=MEDIA_API_URL, api_key=MEDIA_API_KEY,
                              provider="env_primary", priority=10)

        extra = os.getenv("MEDIA_API_BACKUP_URLS", "").strip()
        if extra:
            for i, entry in enumerate(extra.split(","), start=1):
                parts = entry.strip().split("|", 1)
                url = parts[0].strip().rstrip("/")
                key = parts[1].strip() if len(parts) > 1 else ""
                if url and not any(ep.url == url for ep in self._endpoints):
                    self.add_endpoint(url=url, api_key=key,
                                     provider=f"env_backup_{i}", priority=50 + i)


_registry: Optional[EndpointRegistry] = None


def get_registry() -> EndpointRegistry:
    global _registry
    if _registry is None:
        _registry = EndpointRegistry()
        _registry.load()
        _registry.seed_from_env()
    return _registry
