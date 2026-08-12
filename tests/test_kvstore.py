"""Tests for the Redis persistence backend (kvstore) + a store wired through
it. Uses a fake in-memory Redis (no server). Proves: round-trip of list/dict
blobs, enabled() gating, errors never raise (degrade to local file), and that a
store's data SURVIVES a simulated redeploy (fresh in-memory state + gone local
file, data restored from Redis).

Run: .venv/bin/python tests/test_kvstore.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS  {name}")
    else:
        failed += 1
        print(f"FAIL  {name}")


import bot.utils.kvstore as kv


class FakeRedis:
    def __init__(self):
        self.d = {}

    def ping(self):
        return True

    def get(self, k):
        return self.d.get(k)

    def set(self, k, v):
        self.d[k] = v


def _use(client):
    kv._client = client
    kv._checked = True


# ── Upstash TLS auto-upgrade ────────────────────────────────────────────────
check("upstash redis:// -> rediss://",
      kv._normalize_url("redis://default:pw@x.upstash.io:6379") == "rediss://default:pw@x.upstash.io:6379")
check("already rediss:// unchanged",
      kv._normalize_url("rediss://default:pw@x.upstash.io:6379") == "rediss://default:pw@x.upstash.io:6379")
check("non-upstash redis:// unchanged (no forced TLS)",
      kv._normalize_url("redis://localhost:6379") == "redis://localhost:6379")

# ── round-trip + gating ─────────────────────────────────────────────────────
_use(FakeRedis())
check("enabled() true with client", kv.enabled() is True)
kv.save("t", [1, 2, 3])
check("list round-trips", kv.load("t") == [1, 2, 3])
kv.save("d", {"a": 1, "b": [2]})
check("dict round-trips", kv.load("d") == {"a": 1, "b": [2]})
check("missing key -> None", kv.load("nope") is None)

# disabled -> inert
_use(None)
check("enabled() false without client", kv.enabled() is False)
check("load disabled -> None", kv.load("t") is None)
kv.save("t", [9])  # no-op, must not raise
check("save disabled is a no-op", True)


# ── errors never raise, and disable the broken client ───────────────────────
class BoomRedis(FakeRedis):
    def set(self, k, v):
        raise RuntimeError("redis down")

    def get(self, k):
        raise RuntimeError("redis down")


_use(BoomRedis())
kv.save("x", [1])
check("save swallows error", True)
check("save error disables client", kv._client is None)
_use(BoomRedis())
check("load swallows error -> None", kv.load("x") is None)
check("load error disables client", kv._client is None)


# ── a wired store survives a simulated redeploy ─────────────────────────────
import bot.utils.greetings as g

shared = FakeRedis()
_use(shared)

d1 = tempfile.mkdtemp()
g.GREETINGS_FILE = os.path.join(d1, "greetings.json")
g._enabled.clear(); g._loaded = False
g.set_enabled(111, True)     # write-through
g.set_enabled(222, True)
check("write-through to redis", set(kv.load("greetings")) == {111, 222})

# Simulate a Railway redeploy: fresh in-memory state, local file GONE,
# same Redis. Data must come back from Redis.
_use(shared)  # Redis persists across the "redeploy"
g._enabled.clear(); g._loaded = False
g.GREETINGS_FILE = os.path.join(tempfile.mkdtemp(), "greetings.json")  # no file
check("restored after redeploy: 111 on", g.is_enabled(111) is True)
check("restored after redeploy: 222 on", g.is_enabled(222) is True)
check("unset chat still off", g.is_enabled(999) is False)

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
