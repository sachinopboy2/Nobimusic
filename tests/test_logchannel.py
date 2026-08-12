"""Tests for the /setlog log-channel subsystem. Offline — no Telegram.

Run: .venv/bin/python tests/test_logchannel.py
"""
import asyncio
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["LOG_CHAT_FILE"] = os.path.join(tempfile.mkdtemp(), "log_chat.json")

from bot.utils import logchannel as lc

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append(bool(cond))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


# Platform detection — known platforms, aliases, unknown fallback
cases = {
    "https://www.instagram.com/reel/abc/": "instagram",
    "https://youtu.be/xyz": "youtube",
    "https://m.youtube.com/watch?v=x": "youtube",
    "https://pin.it/abc": "pinterest",
    "https://www.pinterest.com/pin/1/": "pinterest",
    "https://vm.tiktok.com/xyz": "tiktok",
    "https://x.com/user/status/1": "twitter",
    "https://fb.watch/abc": "facebook",
    "https://redd.it/abc": "reddit",
    "https://open.spotify.com/track/x": "spotify",
    "soundcloud.com/artist/track": "soundcloud",   # unknown → 2nd-level domain
    "https://vimeo.com/12345": "vimeo",            # unknown → 2nd-level domain
}
for url, want in cases.items():
    got = lc.detect_platform(url)
    check(f"detect {want}", got == want, f"url={url} got={got}")

# Emoji lookup: known platform → custom emoji; unknown → plain fallback
check("emoji known platform", 'emoji id="5438312655624380182"' in lc.platform_emoji_html("instagram"))
check("emoji unknown platform fallback", lc.platform_emoji_html("vimeo") == "📥")

# Template: dynamic platform + emoji, no hardcoding; success and failure
user = types.SimpleNamespace(id=42, first_name="Test", last_name=None)
ok_log = lc.build_download_log(user=user, url="https://youtu.be/x",
                               media_type="video", ok=True,
                               file_size=5 * 1024 * 1024, started=None)
check("success log has platform name", "YouTube" in ok_log)
check("success log has platform emoji", 'emoji id="5832211377720137226"' in ok_log)
check("success log status", "Status: SUCCESS" in ok_log and "delivered" in ok_log)
check("success log size humanized", "5.0 MB" in ok_log)
check("success log user", 'tg://user?id=42' in ok_log and "User ID: 42" in ok_log)

fail_log = lc.build_download_log(user=user, url="https://vimeo.com/1",
                                 media_type="video", ok=False,
                                 error="login <wall>")
check("failure log status", "Status: FAILED" in fail_log)
check("failure log reason escaped", "login &lt;wall&gt;" in fail_log)
check("failure log unknown platform", "Vimeo" in fail_log and "📥" in fail_log)

# Persistence: set → get → reload from disk
check("no log chat initially", lc.get_log_chat() is None)
lc.set_log_chat(-100123)
check("set/get", lc.get_log_chat() == -100123)
lc._state.clear(); lc._loaded = False   # simulate restart
check("survives restart", lc.get_log_chat() == -100123)
lc.set_log_chat(-100456)                # replace previous
lc._state.clear(); lc._loaded = False
check("replace previous", lc.get_log_chat() == -100456)

# clear_log_chat: removes, persists removal, idempotent
check("clear returns True when set", lc.clear_log_chat() is True)
check("cleared", lc.get_log_chat() is None)
lc._state.clear(); lc._loaded = False   # simulate restart
check("clear survives restart", lc.get_log_chat() is None)
check("clear idempotent", lc.clear_log_chat() is False)
lc.set_log_chat(-100456)                # restore for the send tests below

# send_log: no-op without client errors when chat set; never raises
class FakeClient:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))

class BrokenClient:
    async def send_message(self, *a, **kw):
        raise RuntimeError("boom")

fc = FakeClient()
asyncio.run(lc.log_download(fc, user=user, url="https://youtu.be/x",
                            media_type="video", ok=True, file_size=1024))
check("send_log delivers to configured chat",
      fc.sent and fc.sent[0][0] == -100456)
try:
    asyncio.run(lc.send_log(BrokenClient(), "x"))
    check("send_log never raises", True)
except Exception as exc:
    check("send_log never raises", False, repr(exc))

fails = RESULTS.count(False)
print(f"\n{len(RESULTS) - fails}/{len(RESULTS)} passed")
sys.exit(1 if fails else 0)
