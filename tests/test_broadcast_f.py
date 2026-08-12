"""/broadcast_F handler + filter isolation (no live Telegram)."""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pyrogram import filters

from bot.plugins import broadcast_f as bf

failed = 0


def check(name, ok):
    global failed
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1


class _Status:
    def __init__(self):
        self.text = None

    async def edit_text(self, text, **kw):
        self.text = text


class _Msg:
    def __init__(self, *, uid=1, reply=None, text="/broadcast_F"):
        self.from_user = SimpleNamespace(id=uid)
        self.reply_to_message = reply
        self.text = text
        self.caption = None
        self.command = None
        self.replies = []
        self.status = _Status()

    async def reply_text(self, text, **kw):
        self.replies.append(text)
        return self.status


class _Client:
    def __init__(self, fail_on=()):
        self.me = SimpleNamespace(username="")
        self.calls = []
        self._fail_on = set(fail_on)

    async def forward_messages(self, **kw):
        self.calls.append(kw)
        if kw["chat_id"] in self._fail_on:
            raise RuntimeError("boom")
        return SimpleNamespace(id=999, chat=SimpleNamespace(id=kw["chat_id"], type=None))


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def main():
    # patch collaborators on the module namespace (no live services)
    async def sudo_yes(uid): return True
    async def sudo_no(uid): return False
    async def owners(): return {1}
    async def no_pin(client, msg): return False

    bf.is_sudo = sudo_yes
    bf.get_owner_ids = owners
    bf._maybe_pin = no_pin
    bf.chats.all_chats = lambda: [-100111, -100222, 333]
    bf._DELAY_BETWEEN_SENDS = 0  # don't sleep in tests

    # 1) reply present → native forward to every target, no hide_sender_name
    c = _Client()
    m = _Msg(reply=SimpleNamespace(id=42, chat=SimpleNamespace(id=-100999)))
    run(bf.broadcast_forward_command(c, m))
    check("forwards to all 3 targets", len(c.calls) == 3)
    check("uses NATIVE forward (no hide_sender_name)",
          all("hide_sender_name" not in kw for kw in c.calls))
    check("forwards the original replied message",
          all(kw["from_chat_id"] == -100999 and kw["message_ids"] == 42 for kw in c.calls))
    check("summary reports Sent: 3", "Sent:</b> 3" in (m.status.text or ""))

    # 2) no reply → usage prompt, nothing forwarded
    c2 = _Client()
    m2 = _Msg(reply=None)
    run(bf.broadcast_forward_command(c2, m2))
    check("no-reply → nothing forwarded", len(c2.calls) == 0)
    check("no-reply → tells user to reply",
          any("Reply to any message" in r for r in m2.replies))

    # 3) non-sudo → blocked, nothing forwarded
    bf.is_sudo = sudo_no
    c3 = _Client()
    m3 = _Msg(reply=SimpleNamespace(id=1, chat=SimpleNamespace(id=-1)))
    run(bf.broadcast_forward_command(c3, m3))
    check("non-sudo blocked", len(c3.calls) == 0 and any("Sudo only" in r for r in m3.replies))
    bf.is_sudo = sudo_yes

    # 4) one destination fails → others still forwarded, failure counted
    c4 = _Client(fail_on={-100222})
    m4 = _Msg(reply=SimpleNamespace(id=7, chat=SimpleNamespace(id=-100999)))
    run(bf.broadcast_forward_command(c4, m4))
    check("continues past a failing destination", len(c4.calls) == 3)
    check("failure reflected in summary",
          "Sent:</b> 2" in (m4.status.text or "") and "Failed:</b> 1" in (m4.status.text or ""))

    # 5) command-filter isolation: /broadcast_F ≠ /broadcast
    bcast = filters.command("broadcast")
    bcast_f = filters.command("broadcast_F")
    cl = SimpleNamespace(me=SimpleNamespace(username=""))

    def matches(flt, text):
        return run(flt(cl, _Msg(text=text)))

    check("/broadcast_F matches broadcast_F filter", matches(bcast_f, "/broadcast_F"))
    check("/broadcast_F does NOT match broadcast filter", not matches(bcast, "/broadcast_F"))
    check("/broadcast matches broadcast filter", matches(bcast, "/broadcast hello"))
    check("/broadcast does NOT match broadcast_F filter", not matches(bcast_f, "/broadcast hello"))

    print(f"\n{'FAILED' if failed else 'OK'}: {failed} failure(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
