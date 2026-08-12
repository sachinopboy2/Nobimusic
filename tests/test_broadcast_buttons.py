"""/broadcast reply behavior (no live Telegram).

Reply-based broadcasts are delivered as NATIVE Telegram forwards — the replied
message is forwarded as-is (Forwarded-from header + inline keyboard + media +
caption + entities preserved server-side), never reconstructed. Crucially the
forward uses NO hide_sender_name/drop_author, because that flag turns the
forward into a copy and strips the inline keyboard.

Text-mode broadcasts (`/broadcast <text>`, no reply) can still carry buttons
the admin authors with the buttonurl:// syntax.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pyrogram.errors import PeerIdInvalid
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.plugins import broadcast as b

failed = 0


def check(name, ok):
    global failed
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _markup(rows):
    return InlineKeyboardMarkup(rows)


def _reply(chat_id=-100999, mid=42, reply_markup=None):
    return SimpleNamespace(id=mid, chat=SimpleNamespace(id=chat_id), reply_markup=reply_markup)


class _Client:
    def __init__(self):
        self.calls = []          # (method, chat_id, kwargs) for send_*
        self.forward_calls = []  # kwargs for forward_messages
        self.raise_on = {}       # method -> [exc_or_None per call]

    async def forward_messages(self, **kw):
        self.forward_calls.append(kw)
        seq = self.raise_on.get("forward_messages")
        if seq:
            exc = seq.pop(0)
            if exc is not None:
                raise exc
        return SimpleNamespace(id=777, chat=SimpleNamespace(id=kw["chat_id"], type=None))

    async def send_message(self, chat_id, text, **kw):
        self.calls.append(("send_message", chat_id, {"text": text, **kw}))
        return SimpleNamespace(id=555, chat=SimpleNamespace(id=chat_id, type=None))


def main():
    url_btn = InlineKeyboardButton("Open", url="https://example.com")
    cb_btn = InlineKeyboardButton("Click", callback_data="cb_1")
    kb = _markup([[url_btn, cb_btn]])

    # 1) reply WITH a keyboard -> NATIVE forward (keyboard preserved server-side)
    c = _Client()
    reply = _reply(reply_markup=kb)
    sent, err = run(b._send_one(c, 111, reply=reply, body="", body_entities=[], markup=kb))
    check("reply+kb -> forward_messages used", len(c.forward_calls) == 1)
    check("reply+kb -> NO send_* reconstruction", len(c.calls) == 0)
    check("reply+kb -> NATIVE forward (no hide_sender_name/drop_author)",
          "hide_sender_name" not in c.forward_calls[0]
          and "drop_author" not in c.forward_calls[0])
    check("reply+kb -> forwards the exact replied message",
          c.forward_calls[0].get("from_chat_id") == -100999
          and c.forward_calls[0].get("message_ids") == 42)
    check("reply+kb -> silent forward", c.forward_calls[0].get("disable_notification") is True)
    check("reply+kb -> returns the forwarded message", sent is not None and err is None)

    # 2) reply WITHOUT a keyboard -> same native forward path (type-agnostic)
    c2 = _Client()
    run(b._send_one(c2, 222, reply=_reply(reply_markup=None), body="", body_entities=[], markup=None))
    check("reply(no kb) -> forward_messages used", len(c2.forward_calls) == 1)
    check("reply(no kb) -> NO send_* reconstruction", len(c2.calls) == 0)
    check("reply(no kb) -> native forward (no hide_sender_name)",
          "hide_sender_name" not in c2.forward_calls[0])

    # 3) chat-level error on forward -> propagates to the caller (loop handles it)
    c3 = _Client()
    c3.raise_on["forward_messages"] = [PeerIdInvalid()]
    raised = False
    try:
        run(b._send_one(c3, 333, reply=_reply(), body="", body_entities=[], markup=None))
    except PeerIdInvalid:
        raised = True
    check("forward chat-level error propagates", raised)

    # 4) text-mode (no reply) -> send_message; no forward
    c4 = _Client()
    run(b._send_one(c4, 444, reply=None, body="hello", body_entities=[], markup=None))
    check("text -> send_message used", [m for m, _, _ in c4.calls] == ["send_message"])
    check("text -> no forward", len(c4.forward_calls) == 0)

    # ---- end-to-end through broadcast_command ----
    class _Status:
        def __init__(self):
            self.text = None

        async def edit_text(self, text, **kw):
            self.text = text

    class _Cmd:
        def __init__(self, reply, text="/broadcast", command=("broadcast",)):
            self.from_user = SimpleNamespace(id=1)
            self.reply_to_message = reply
            self.text = text
            self.command = list(command)
            self.entities = None
            self.replies = []
            self.status = _Status()

        async def reply_text(self, text, **kw):
            self.replies.append(text)
            return self.status

    saved = (b.is_sudo, b.get_owner_ids, b._maybe_pin, b._DELAY_BETWEEN_SENDS, b.chats.all_chats)

    async def _sudo_yes(uid):
        return True

    async def _owners():
        return {1}

    async def _no_pin(cl, m):
        return False

    b.is_sudo = _sudo_yes
    b.get_owner_ids = _owners
    b._maybe_pin = _no_pin
    b._DELAY_BETWEEN_SENDS = 0
    b.chats.all_chats = lambda: [123, 456]
    try:
        # 5) reply broadcast -> native forward to every target, nothing reconstructed
        ce = _Client()
        run(b.broadcast_command(ce, _Cmd(_reply(reply_markup=kb))))
        check("e2e reply: forwarded to both targets", len(ce.forward_calls) == 2)
        check("e2e reply: never reconstructs (no send_*)", len(ce.calls) == 0)
        check("e2e reply: native forward (no hide_sender_name)",
              all("hide_sender_name" not in kw for kw in ce.forward_calls))

        # 6) text + typed buttons -> send_message carries a bot-built URL button
        cmd_text = "/broadcast Hello there [Join](buttonurl://https://t.me/mychat)"
        ct = _Client()
        run(b.broadcast_command(ct, _Cmd(None, text=cmd_text,
                                         command=["broadcast", "Hello", "..."])))
        tsends = [c for c in ct.calls if c[0] == "send_message"]
        check("e2e typed: send_message for both targets", len(tsends) == 2)
        check("e2e typed: button syntax stripped from text",
              all(c[2].get("text") == "Hello there" for c in tsends))
        got_kb = tsends[0][2].get("reply_markup") if tsends else None
        btns = [(bt.text, bt.url) for row in (got_kb.inline_keyboard if got_kb else []) for bt in row]
        check("e2e typed: URL button built + attached", btns == [("Join", "https://t.me/mychat")])
        check("e2e typed: no forward for text broadcast", len(ct.forward_calls) == 0)
    finally:
        (b.is_sudo, b.get_owner_ids, b._maybe_pin, b._DELAY_BETWEEN_SENDS, b.chats.all_chats) = saved

    # 7) button-syntax parser unit checks (text path)
    t1, _, m1 = b._parse_button_markup("Promo!\n[Open](buttonurl://https://x.com)", [])
    check("parse: text cleaned of button syntax", t1 == "Promo!")
    check("parse: URL button extracted",
          [[(x.text, x.url) for x in r] for r in m1.inline_keyboard] == [[("Open", "https://x.com")]])
    _, _, m2 = b._parse_button_markup(
        "[A](buttonurl://https://a.com) [B](buttonurl://https://b.com:same)", [])
    check("parse: ':same' groups buttons on one row",
          len(m2.inline_keyboard) == 1 and len(m2.inline_keyboard[0]) == 2)
    t3, _, m3 = b._parse_button_markup("just a normal message", [])
    check("parse: plain text unchanged, no markup", t3 == "just a normal message" and m3 is None)

    print(f"\n{'FAILED' if failed else 'OK'}: {failed} failure(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
