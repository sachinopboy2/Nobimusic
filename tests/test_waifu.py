"""Offline tests for the /waifu feature (pure logic + isolated persistence).

Telegram I/O in bot/plugins/waifu.py isn't exercised here (no live client);
everything testable without the API is covered.
"""
import os
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Isolate persistence to a temp file BEFORE importing the module.
_TMP = tempfile.mkdtemp(prefix="waifu_test_")
os.environ["WAIFU_FILE"] = os.path.join(_TMP, "waifu.json")
os.environ.pop("REDIS_URL", None)  # force local-JSON path (kvstore disabled)

from bot.utils import waifu  # noqa: E402

failed = 0


def check(name, ok):
    global failed
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1


def _profile(**over):
    p = {
        "chat_id": -100, "waifu_id": 42, "waifu_name": "Aki",
        "waifu_username": "aki", "assigned_at": time.time(), "photo_id": None,
        "layout": 1, "bond": 73, "chemistry": "★★★★☆",
        "relationship": "Soulmates", "quote": "Destiny has spoken.",
    }
    p.update(over)
    return p


def main():
    # 1) generated values always in range / from pools
    ok = True
    for _ in range(500):
        v = waifu.new_profile_values()
        ok &= (v["layout"] in waifu.LAYOUT_IDS and 1 <= v["bond"] <= 100
               and v["chemistry"] in waifu.CHEMISTRY
               and v["relationship"] in waifu.RELATIONSHIPS
               and v["quote"] in waifu.QUOTES)
    check("new_profile_values within pools/ranges (500x)", ok)

    # 2) expiry is strictly elapsed-time, boundary at 86400
    now = 1_000_000.0
    check("active just under 24h", waifu.is_active({"assigned_at": now - 86_399}, now))
    check("expired exactly at 24h", not waifu.is_active({"assigned_at": now - 86_400}, now))
    check("expired past 24h", not waifu.is_active({"assigned_at": now - 90_000}, now))
    check("missing timestamp => expired", not waifu.is_active({}, now))

    # 3) eligibility
    check("normal user eligible", waifu.is_eligible(SimpleNamespace(id=1, is_bot=False, is_deleted=False)))
    check("bot rejected", not waifu.is_eligible(SimpleNamespace(id=1, is_bot=True, is_deleted=False)))
    check("deleted rejected", not waifu.is_eligible(SimpleNamespace(id=1, is_bot=False, is_deleted=True)))
    check("None rejected", not waifu.is_eligible(None))

    # 4) every layout renders with the core fields present
    all_ok = True
    for lid in waifu.LAYOUT_IDS:
        card = waifu.render_card(_profile(layout=lid))
        all_ok &= ('href="tg://user?id=42"' in card and "Soulmates" in card
                   and "★★★★☆" in card and "Destiny has spoken." in card
                   and "73%" in card)
    check("all 8 layouts render core fields", all_ok)

    # 4b) no leftover reference branding in any layout (default WAIFU_BRAND unset)
    branded = all("Nobara" not in waifu.render_card(_profile(layout=l)) for l in waifu.LAYOUT_IDS)
    check("no 'Nobara' reference in any layout", branded)

    # 4c) premium custom-emoji present in every card and the owner header
    prem = all('<emoji id="' in waifu.render_card(_profile(layout=l)) for l in waifu.LAYOUT_IDS)
    check("premium custom-emoji in every layout", prem)
    check("premium custom-emoji in owner header", '<emoji id="' in waifu.owner_header(waifu.mention(9, "Me")))

    # 5) username line shown only when present, never an empty gap
    with_u = waifu.render_card(_profile(layout=1, waifu_username="aki"))
    no_u = waifu.render_card(_profile(layout=1, waifu_username=None))
    check("username line shown when present", "@aki" in with_u)
    check("username line omitted when absent", "@" not in no_u and "🆔" not in no_u)
    check("no empty username gap", "\n\n🆔" not in with_u and "  \n" not in no_u)

    # 6) HTML safety — a hostile display name is escaped inside the mention
    evil = waifu.render_card(_profile(waifu_name="<b>&x</b>"))
    check("waifu name HTML-escaped", "&lt;b&gt;&amp;x&lt;/b&gt;" in evil and "<b>&x" not in evil)

    # 7) bond bar fills proportionally and stays within cell count
    b0 = waifu.render_card(_profile(layout=3, bond=0))
    b100 = waifu.render_card(_profile(layout=3, bond=100))
    check("bar empty at 0%", "░░░░░░░░░░ 0%" in b0)
    check("bar full at 100%", "██████████ 100%" in b100)

    # 8) owner header names the sender (shown on every response); footer present
    check("owner header shows sender mention", 'id=7">Me</a>' in waifu.owner_header(waifu.mention(7, "Me")))
    check("owner header labels the waifu as theirs", "'s Waifu" in waifu.owner_header(waifu.mention(7, "Me")))
    check("new-assignment footer present", "Fate has made" in waifu.footer_new())

    # 9) persistence round-trip survives a simulated restart (per-group key)
    waifu.put_profile(999, -1001, _profile(waifu_id=555, bond=88))
    waifu._loaded = False          # simulate process restart
    waifu._profiles.clear()
    reloaded = waifu.get_profile(999, -1001)
    check("profile persisted to JSON and reloaded", reloaded is not None
          and reloaded["waifu_id"] == 555 and reloaded["bond"] == 88)
    check("unknown user has no profile", waifu.get_profile(123456, -1001) is None)

    # 9b) same user, DIFFERENT group -> independent (no cross-group leak)
    check("same user other group has no bond", waifu.get_profile(999, -1002) is None)
    waifu.put_profile(999, -1002, _profile(waifu_id=777, bond=10))
    check("group A bond unchanged by group B", waifu.get_profile(999, -1001)["waifu_id"] == 555)
    check("group B has its own bond", waifu.get_profile(999, -1002)["waifu_id"] == 777)

    print(f"\n{'FAILED' if failed else 'OK'}: {failed} failure(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
