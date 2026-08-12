"""Background health monitor for Media API endpoints.

Runs as an asyncio task: periodically probes every registered endpoint,
triggers failover on persistent failures, and restores endpoints that
come back online. Sends admin notifications via the log channel.
"""

import asyncio
import logging
import time
from typing import Optional

import aiohttp

from bot.utils.api_registry import (
    Endpoint,
    EndpointRegistry,
    get_registry,
    RESTORE_CHECK_INTERVAL_S,
)

logger = logging.getLogger("WarbornMusic.api_health")

CHECK_INTERVAL_S = int(__import__("os").getenv("API_HEALTH_INTERVAL", "45"))
PROBE_TIMEOUT_S = 10

_monitor_task: Optional[asyncio.Task] = None


async def probe_endpoint(ep: Endpoint) -> tuple[bool, str]:
    try:
        timeout = aiohttp.ClientTimeout(total=PROBE_TIMEOUT_S)
        headers = {}
        if ep.api_key:
            headers["X-API-Key"] = ep.api_key
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(f"{ep.url}/health", headers=headers) as resp:
                if 200 <= resp.status < 300:
                    return True, f"HTTP {resp.status}"
                return False, f"HTTP {resp.status}"
    except aiohttp.ClientConnectorError as exc:
        return False, f"unreachable: {exc}"
    except asyncio.TimeoutError:
        return False, f"timeout ({PROBE_TIMEOUT_S}s)"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


async def _notify_admin(client, message: str) -> None:
    try:
        from bot.utils.logchannel import get_log_chat, send_log
        chat_id = get_log_chat()
        if chat_id:
            await send_log(client, f"🔧 <b>API Health Monitor</b>\n\n{message}")
    except Exception:
        logger.debug("api_health: admin notification failed (no log channel?)")


async def _launch_embedded(registry: EndpointRegistry, client) -> bool:
    """Start the embedded local API server and register it in the registry."""
    try:
        from bot.utils.embedded_api import ensure_running, is_running
        if is_running():
            return False
        url, key = await ensure_running()
        registry.add_endpoint(url=url, api_key=key,
                              provider="embedded_local", priority=999)
        logger.info("api_health: embedded server registered at %s", url)
        return True
    except Exception:
        logger.exception("api_health: failed to start embedded server")
        return False


async def _check_cycle(registry: EndpointRegistry, client) -> None:
    if not registry.endpoints:
        return

    active_before = registry.active

    for ep in registry.endpoints:
        if ep.healthy:
            ok, detail = await probe_endpoint(ep)
            if ok:
                registry.record_success(ep.url)
            else:
                next_ep = registry.record_failure(ep.url)
                if not ep.healthy:
                    await _notify_admin(
                        client,
                        f"⚠️ <b>Endpoint DOWN</b>\n"
                        f"<code>{ep.url}</code> ({ep.provider})\n"
                        f"Reason: {detail}\n"
                        f"Fails: {ep.fail_count}\n"
                        f"Cooldown: {ep.cooldown_remaining:.0f}s\n"
                        f"Next active: <code>{next_ep.url if next_ep else 'NONE'}</code>"
                    )

    stale = registry.get_stale(max_age_s=RESTORE_CHECK_INTERVAL_S)
    for ep in stale:
        ok, detail = await probe_endpoint(ep)
        if ok:
            registry.restore_endpoint(ep.url)
            await _notify_admin(
                client,
                f"✅ <b>Endpoint RESTORED</b>\n"
                f"<code>{ep.url}</code> ({ep.provider})\n"
                f"Was down since: {time.strftime('%H:%M:%S', time.localtime(ep.last_fail))}"
            )
        else:
            ep.last_check = time.time()
            registry.save()

    active_after = registry.active
    if active_before and active_after and active_before.url != active_after.url:
        await _notify_admin(
            client,
            f"🔄 <b>Failover</b>\n"
            f"From: <code>{active_before.url}</code>\n"
            f"To: <code>{active_after.url}</code>"
        )

    if active_before and not active_after:
        launched = await _launch_embedded(registry, client)
        msg = (
            "🚨 <b>ALL endpoints DOWN</b>\n"
            + ("🔧 Embedded local API server started as fallback.\n" if launched else "")
            + "Endpoints will be re-probed automatically."
        )
        await _notify_admin(client, msg)


async def _monitor_loop(client) -> None:
    registry = get_registry()
    logger.info("api_health: monitor started (interval=%ds, %d endpoint(s))",
                CHECK_INTERVAL_S, len(registry.endpoints))
    while True:
        try:
            await _check_cycle(registry, client)
        except Exception:
            logger.exception("api_health: check cycle failed")
        await asyncio.sleep(CHECK_INTERVAL_S)


def start_monitor(client) -> Optional[asyncio.Task]:
    global _monitor_task
    registry = get_registry()
    if not registry.endpoints:
        logger.info("api_health: no endpoints registered, monitor not started")
        return None
    _monitor_task = asyncio.create_task(_monitor_loop(client))
    _monitor_task.add_done_callback(
        lambda t: logger.error(
            "api_health: monitor loop EXITED: %r",
            t.exception() if not t.cancelled() else "cancelled",
        )
    )
    return _monitor_task


def stop_monitor() -> None:
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        _monitor_task = None
