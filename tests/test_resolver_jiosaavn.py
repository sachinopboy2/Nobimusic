"""Guard test: the JioSaavn fallback must not play an unrelated (Hindi) track
for a Western query. _query_matches gates it; a non-matching hit is rejected
(so the resolver reports 'not found' instead of a wrong song), while a genuine
match still passes.

Run: .venv/bin/python tests/test_resolver_jiosaavn.py
"""
import asyncio
import os
import sys

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


import bot.utils.resolver as r
import bot.utils.saavn as saavn

# ── _query_matches ──────────────────────────────────────────────────────────
check("exact match passes", r._query_matches("blinding lights", "Blinding Lights - The Weeknd"))
check("title+artist match passes", r._query_matches("believer imagine dragons", "Believer - Imagine Dragons"))
check("unrelated hindi song rejected", r._query_matches("blinding lights", "Tum Hi Ho - Arijit Singh") is False)
check("totally different rejected", r._query_matches("shape of you", "Kesariya - Arijit Singh") is False)
check("partial (half tokens) passes", r._query_matches("blinding lights the weeknd", "Blinding Lights - The Weeknd"))
check("empty query not blocked", r._query_matches("", "anything") is True)

# ── _via_jiosaavn applies the guard ─────────────────────────────────────────
def _stub(label):
    async def _f(query):
        return ("https://cdn/x.mp3", label, 200)
    return _f

# matching hit -> returned
saavn.search_jiosaavn = _stub("Blinding Lights - The Weeknd")
res = asyncio.run(r._via_jiosaavn("blinding lights"))
check("matching JioSaavn hit accepted", res[0] == "https://cdn/x.mp3")

# non-matching (hindi) hit -> rejected -> (None, "", None)
saavn.search_jiosaavn = _stub("Tum Hi Ho - Arijit Singh")
res = asyncio.run(r._via_jiosaavn("blinding lights"))
check("non-matching JioSaavn hit rejected", res[0] is None)

# genuine Indian request still works
saavn.search_jiosaavn = _stub("Kesariya - Arijit Singh")
res = asyncio.run(r._via_jiosaavn("kesariya arijit singh"))
check("genuine Indian query still resolves via JioSaavn", res[0] == "https://cdn/x.mp3")

print(f"\n{passed}/{passed + failed} passed")
sys.exit(1 if failed else 0)
