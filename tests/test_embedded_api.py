"""Tests for the embedded local API server."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aiohttp
from bot.utils.embedded_api import EmbeddedApiServer, is_running

passed = 0


def check(label, condition):
    global passed
    tag = "PASS" if condition else "FAIL"
    print(f"{tag}  {label}")
    if not condition:
        raise AssertionError(label)
    passed += 1


async def run_tests():
    server = EmbeddedApiServer()

    check("not running initially", not server.running)

    url, key = await server.start()
    check("running after start", server.running)
    check("url has port", "127.0.0.1" in url)
    check("key is 64 hex chars", len(key) == 64)

    # Health endpoint (no auth needed)
    async with aiohttp.ClientSession() as s:
        async with s.get(f"{url}/health") as resp:
            check("health returns 200", resp.status == 200)
            body = await resp.json()
            check("health has provider=embedded", body.get("provider") == "embedded")

    # Download endpoint without auth
    async with aiohttp.ClientSession() as s:
        async with s.post(f"{url}/download", json={"url": "https://example.com"}) as resp:
            check("download without key returns 401", resp.status == 401)

    # Download endpoint with wrong key
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{url}/download",
            json={"url": "https://example.com"},
            headers={"X-API-Key": "wrong"},
        ) as resp:
            check("download with wrong key returns 401", resp.status == 401)

    # Download endpoint with correct key but missing url
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{url}/download",
            json={},
            headers={"X-API-Key": key},
        ) as resp:
            check("download with missing url returns 400", resp.status == 400)

    # Download endpoint with correct key + invalid JSON
    async with aiohttp.ClientSession() as s:
        async with s.post(
            f"{url}/download",
            data=b"not json",
            headers={"X-API-Key": key, "Content-Type": "application/json"},
        ) as resp:
            check("download with invalid JSON returns 400", resp.status == 400)

    # Idempotent start
    url2, key2 = await server.start()
    check("idempotent start same url", url2 == url)
    check("idempotent start same key", key2 == key)

    await server.stop()
    check("stopped after stop", not server.running)


asyncio.run(run_tests())
print(f"\n{passed}/{passed} passed")
