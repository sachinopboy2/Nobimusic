"""Offline tests for /all reply-forwarding + backward compatibility.

Drives all_tag._run with a fake client to assert: reply mode replies to the
original message for every batch, additional text becomes a "📢" header, and
non-reply behavior is unchanged.
"""
import asyncio
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bot.plugins import all_tag  # noqa: E402

all_tag._BATCH_PACING = 0  # no real waiting between batches
failed = 0


def check(name, ok):
    global failed
    print(("PASS  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1


class FakeClient:
    def __init__(self, users):
        self._users = users
        self.sends = []  # list of (body, reply_to_message_id)

    async def get_chat_members(self, chat_id):
        for u in self._users:
            yield SimpleNamespace(user=u)

    async def send_message(self, chat_id, body, parse_mode=None,
                           reply_to_message_id=None, disable_web_page_preview=None):
        self.sends.append((body, reply_to_message_id))
        return SimpleNamespace(id=len(self.sends))


class FakeText:
    """Stand-in for pyrogram's Str: truthy + an .html property."""
    def __init__(self, html):
        self._html = html

    def __bool__(self):
        return bool(self._html)

    @property
    def html(self):
        return self._html


def _users(n):
    return [SimpleNamespace(id=i, first_name=f"U{i}", last_name="",
                            username=f"u{i}", is_bot=False, is_deleted=False)
            for i in range(1, n + 1)]


async def _run(client, reply_first, custom, sender="@admin"):
    all_tag._active[-100] = {"cancelled": False}
    await all_tag._run(client, -100, reply_first, custom, all_tag._active[-100], sender=sender)


def main():
    # 1) reply + text -> premium broadcast card, every batch replies to original
    c = FakeClient(_users(7))  # 7 members -> 2 batches
    custom_html = 'Everyone join <tg-emoji emoji-id="123">🎉</tg-emoji>'
    asyncio.run(_run(c, reply_first=123, custom=custom_html, sender="@boss"))
    check("reply mode: 2 batches sent", len(c.sends) == 2)
    check("reply mode: every batch replies to original",
          all(rt == 123 for _, rt in c.sends))
    check("reply mode: broadcast banner on every batch",
          all("<b>Broadcast</b>" in b for b, _ in c.sends))
    check("reply mode: shows admin", all("@boss" in b for b, _ in c.sends))
    check("reply mode: preserves custom text + premium emoji",
          '<tg-emoji emoji-id="123">' in c.sends[0][0] and "Everyone join" in c.sends[0][0])
    check("reply mode: mentions present", "@u1" in c.sends[0][0])

    # 2) reply + no text -> premium card (banner + admin), still replies, no note
    c = FakeClient(_users(3))
    asyncio.run(_run(c, reply_first=555, custom="", sender="@boss"))
    check("reply+no-text: replies to original", c.sends[0][1] == 555)
    check("reply+no-text: premium banner + admin",
          "<b>Broadcast</b>" in c.sends[0][0] and "@boss" in c.sends[0][0])
    check("reply+no-text: mentions present", "@u1" in c.sends[0][0])

    # 3) backward compat: non-reply + text -> 📢 header, no reply target
    c = FakeClient(_users(3))
    asyncio.run(_run(c, reply_first=None, custom="hello"))
    check("non-reply+text: no reply target", c.sends[0][1] is None)
    check("non-reply+text: 📢 header",
          c.sends[0][0].startswith(f"{all_tag.e.MEGA} <b>hello</b>"))

    # 4) plain /all -> premium call-out header + mentions, no reply target
    c = FakeClient(_users(3))
    asyncio.run(_run(c, reply_first=None, custom=""))
    check("plain /all: no reply target", c.sends[0][1] is None)
    check("plain /all: premium header + mentions",
          all_tag.e.PEOPLE in c.sends[0][0] and "Attention, everyone!" in c.sends[0][0]
          and "@u1" in c.sends[0][0])

    # 5) entity preservation: _extract_custom keeps HTML (custom emoji etc.)
    msg = SimpleNamespace(text=FakeText(
        '/all 🚀 <tg-emoji emoji-id="123">🎉</tg-emoji> <b>go</b>'))
    custom = all_tag._extract_custom(msg)
    check("extract keeps custom-emoji tag",
          '<tg-emoji emoji-id="123">' in custom and custom.startswith("🚀"))
    check("extract strips command token", not custom.startswith("/all"))
    check("extract: command only -> empty", all_tag._extract_custom(SimpleNamespace(text=FakeText("/all"))) == "")
    check("extract: /all@bot arg -> arg", all_tag._extract_custom(SimpleNamespace(text=FakeText("/all@WarbornBot hi"))) == "hi")

    # 6) end-to-end: rendered body re-parses with custom-emoji id intact
    from pyrogram.parser.html import HTML
    from pyrogram.enums import MessageEntityType
    body = all_tag._render(custom, ["@u1"])
    parsed = asyncio.run(HTML(None).parse(body))
    ce = [en for en in parsed["entities"]
          if getattr(en, "document_id", None) == 123]
    check("rendered body parses with custom-emoji id 123 preserved", len(ce) == 1)
    check("rendered body keeps mention text", "@u1" in parsed["message"])

    print(f"\n{'FAILED' if failed else 'OK'}: {failed} failure(s)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
