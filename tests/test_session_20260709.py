"""Reproduction + regression tests for session 2026-07-09 findings.

Run: .venv/bin/python tests_repro.py
Exits non-zero on any failure. No live Telegram needed.
"""
import asyncio
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")


# ---------------------------------------------------------------- F1
# Dedup TTL vs poll interval: an event handled by a real-time path must
# still be deduped when the poll loop re-discovers it one full poll
# interval (45s) + processing lag later.
def test_f1():
    from bot.plugins import welcome as w

    w._event_dedup.clear()
    t = [1000.0]
    real_monotonic = w._time.monotonic
    w._time = types.SimpleNamespace(monotonic=lambda: t[0])
    try:
        first = w._event_seen_recently(-100123, 42, "join")   # real-time path fires
        t[0] += w._POLL_INTERVAL_S + 5                        # poll re-discovers it
        second = w._event_seen_recently(-100123, 42, "join")
        check(
            "F1 dedup survives one poll interval",
            (first is False) and (second is True),
            f"first={first} second(seen)={second} TTL={w._DEDUP_TTL_S} poll={w._POLL_INTERVAL_S}",
        )
    finally:
        w._time = types.SimpleNamespace(monotonic=real_monotonic)
        w._event_dedup.clear()


# ---------------------------------------------------------------- F3
# Assistant userbot (a non-bot USER account) must not receive a welcome
# card or farewell from handle_chat_member_event.
def test_f3():
    from bot.plugins import welcome as w
    from pyrogram.enums import ChatMemberStatus
    import bot.client as client_mod

    ASSISTANT_ID = 777000111

    # Simulate a started userbot: userbot.me is set after .start()
    client_mod.userbot.me = types.SimpleNamespace(id=ASSISTANT_ID, is_bot=False)

    sent = []

    async def fake_send_card(client, chat_id, user):
        sent.append(("card", chat_id, user.id))

    async def fake_send_leave(client, chat_id, user):
        sent.append(("leave", chat_id, user.id))

    async def fake_is_admin(client, chat_id, user_id):
        return False

    orig = (w._send_card, w._send_leave, w._is_chat_owner_or_admin,
            w.is_enabled, w.departure_enabled)
    w._send_card, w._send_leave, w._is_chat_owner_or_admin = (
        fake_send_card, fake_send_leave, fake_is_admin,
    )
    w.is_enabled = lambda cid: True          # force greetings ON
    w.departure_enabled = lambda cid: True   # force departures ON
    w._event_dedup.clear()

    def evt(uid, old, new):
        user = types.SimpleNamespace(id=uid, is_bot=False, first_name="A")
        return types.SimpleNamespace(
            chat=types.SimpleNamespace(id=-100555),
            old_chat_member=types.SimpleNamespace(status=old, user=user),
            new_chat_member=types.SimpleNamespace(status=new, user=user),
        )

    async def run():
        # Assistant join + leave — must NOT send anything
        await w.handle_chat_member_event(
            None, evt(ASSISTANT_ID, ChatMemberStatus.LEFT, ChatMemberStatus.MEMBER), "test")
        await w.handle_chat_member_event(
            None, evt(ASSISTANT_ID, ChatMemberStatus.MEMBER, ChatMemberStatus.LEFT), "test")
        assistant_msgs = list(sent)
        # A normal human join — MUST still send (guard against over-filtering)
        w._event_dedup.clear()
        await w.handle_chat_member_event(
            None, evt(123456, ChatMemberStatus.LEFT, ChatMemberStatus.MEMBER), "test")
        return assistant_msgs, list(sent)

    try:
        assistant_msgs, all_msgs = asyncio.run(run())
        check("F3 assistant not welcomed/farewelled", len(assistant_msgs) == 0,
              f"messages fired for assistant: {assistant_msgs}")
        check("F3 normal user still welcomed",
              ("card", -100555, 123456) in all_msgs, f"all={all_msgs}")
    finally:
        (w._send_card, w._send_leave, w._is_chat_owner_or_admin,
         w.is_enabled, w.departure_enabled) = orig
        w._event_dedup.clear()


# ---------------------------------------------------------------- F4
# (F4/F5 removed — they tested the Instagram downloader, which was deleted.)


# ---------------------------------------------------------------- F7
# Poll loop must skip oversized chats (FloodWait protection) but still
# snapshot normal ones.
def test_f7():
    from bot.plugins import welcome as w

    class FakeClient:
        def __init__(self, count, members):
            self._count = count
            self._members = members

        async def get_chat_members_count(self, chat_id):
            return self._count

        def get_chat_members(self, chat_id):
            async def gen():
                for uid, is_bot in self._members:
                    yield types.SimpleNamespace(
                        user=types.SimpleNamespace(id=uid, is_bot=is_bot))
            return gen()

    async def run():
        w._poll_skipped_big.clear()
        big = await w._snapshot_members(FakeClient(5000, []), -100777)
        small = await w._snapshot_members(
            FakeClient(3, [(1, False), (2, False), (99, True)]), -100778)
        return big, small

    big, small = asyncio.run(run())
    check("F7 oversized chat skipped", big is None, f"got={big}")
    check("F7 normal chat snapshotted (bots filtered)",
          small == {1, 2}, f"got={small}")


# ---------------------------------------------------------------- F2
# start.py must hold a strong module-level reference for the poll task.
def test_f2():
    import ast
    tree = ast.parse(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot/start.py")).read())
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bot/start.py")).read()
    check("F2 poll task assigned to module global",
          "_poll_task = asyncio.create_task(poll_participants_forever" in src
          and "_poll_task:" in src.split("async def _run")[0],
          "strong reference present at module scope")


test_f1()
test_f2()
test_f3()
test_f7()

fails = [r for r in RESULTS if not r[1]]
print(f"\n{len(RESULTS) - len(fails)}/{len(RESULTS)} passed")
sys.exit(1 if fails else 0)
