import os

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, ParseMode

from bot.utils.departure import is_enabled as departure_enabled
from bot.utils.greetings import is_enabled
from bot.utils.leave_messages import pick as pick_leave_message
from bot.utils.welcome_image import render_welcome_card

WELCOME_TEMPLATE = (
    # Pyrofork's HTML parser uses <emoji id="..."> not <tg-emoji emoji-id="...">.
    '<emoji id="5460858729962421671">👋</emoji> Welcome, {first_name}!\n\n'
    "━━━━━━━━━━━━━━━\n"
    '<emoji id="5249053508681883137">👤</emoji> Name - {full_name}\n'
    '<emoji id="5818885490065017876">🆔</emoji> User ID - <code>{user_id}</code>\n'
    '<emoji id="6032675574646836901">📛</emoji> Username - {username}\n'
    "━━━━━━━━━━━━━━━\n\n"
    '<emoji id="5969733271305588971">✨</emoji> Your arrival has been successfully registered.\n\n'
    '<emoji id="6269566961168944843">🌐</emoji> Explore, connect, and enjoy everything waiting for you.\n\n'
    '<emoji id="5970041332129863164">💫</emoji> We hope you have an amazing experience and a wonderful time ahead!'
)


def _format(user) -> str:
    first_name = user.first_name or "friend"
    last_name = user.last_name or ""
    full_name = (first_name + " " + last_name).strip() or "Unknown"
    mention = f'<a href="tg://user?id={user.id}">{full_name}</a>'
    username = f"@{user.username}" if user.username else "(no username)"
    return WELCOME_TEMPLATE.format(
        first_name=first_name,
        full_name=mention,
        user_id=user.id,
        username=username,
    )


async def _download_pfp(client, user_id: int) -> str | None:
    try:
        async for photo in client.get_chat_photos(user_id, limit=1):
            os.makedirs("/tmp/warborn_pfps", exist_ok=True)
            path = f"/tmp/warborn_pfps/{user_id}.jpg"
            await client.download_media(photo.file_id, file_name=path)
            return path
    except Exception:
        return None
    return None


async def _send_card(client, chat_id: int, user) -> None:
    first_name = user.first_name or "friend"
    last_name = user.last_name or ""
    display_name = (first_name + " " + last_name).strip() or "friend"
    avatar_path = await _download_pfp(client, user.id)
    try:
        bio = await render_welcome_card(display_name, user.id, avatar_path)
        await client.send_photo(
            chat_id=chat_id,
            photo=bio,
            caption=_format(user),
            parse_mode=ParseMode.HTML,
        )
    finally:
        # Reap the downloaded avatar — nothing else reads it after the
        # card is rendered, and /tmp/warborn_pfps otherwise grows forever.
        if avatar_path:
            try:
                os.remove(avatar_path)
            except OSError:
                pass


async def _is_chat_owner_or_admin(client, chat_id: int, user_id: int) -> bool:
    try:
        member = await client.get_chat_member(chat_id, user_id)
    except Exception as exc:
        # Log instead of silently swallowing — USER_NOT_PARTICIPANT here
        # (common for users who already left) means the "skip departing
        # admins" guard can never confirm admin status, so it returns
        # False and the farewell fires. That's the desired outcome for a
        # leaver, but we want it visible rather than assumed.
        import logging as _l
        _l.getLogger("WarbornMusic.welcome").info(
            "_is_chat_owner_or_admin(chat=%s user=%s) get_chat_member raised: %r",
            chat_id, user_id, exc,
        )
        return False
    return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


@Client.on_message(filters.new_chat_members & filters.group)
async def welcome_new_members(client, message):
    """Legacy path used by regular groups (plain join service message)."""
    import logging as _l
    log = _l.getLogger("WarbornMusic.welcome")
    log.info(
        "welcome_new_members (legacy new_chat_members) FIRED in chat=%s, members=%s",
        message.chat.id if message.chat else None,
        [u.id for u in (message.new_chat_members or [])],
    )
    if not is_enabled(message.chat.id):
        log.info("welcome_new_members: greetings DISABLED for chat=%s — skipping", message.chat.id)
        return
    for user in message.new_chat_members:
        if user.is_bot:
            continue
        if _is_assistant(user.id):
            log.info("welcome_new_members: user %s is the assistant — skipping", user.id)
            continue
        if _event_seen_recently(message.chat.id, user.id, "join"):
            log.info("welcome_new_members: dedup hit for user=%s — already handled", user.id)
            continue
        if await _is_chat_owner_or_admin(client, message.chat.id, user.id):
            log.info("welcome_new_members: user %s is owner/admin — skipping", user.id)
            continue
        try:
            await _send_card(client, message.chat.id, user)
            log.info("welcome_new_members: card sent chat=%s user=%s", message.chat.id, user.id)
        except Exception:
            log.exception("welcome_new_members: _send_card raised")


_JOIN_FROM = (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)
_JOIN_TO = (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED)
_LEAVE_FROM = (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED, ChatMemberStatus.ADMINISTRATOR)
_LEAVE_TO = (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED)


def _mention(user) -> str:
    first_name = user.first_name or "Someone"
    last_name = user.last_name or ""
    full_name = (first_name + " " + last_name).strip() or "Someone"
    return f'<a href="tg://user?id={user.id}">{full_name}</a>'


async def _send_leave(client, chat_id: int, user) -> None:
    template = pick_leave_message(chat_id)
    text = template.format(name=_mention(user))
    await client.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)


@Client.on_message(filters.left_chat_member & filters.group)
async def leave_legacy(client, message):
    import logging as _l
    log = _l.getLogger("WarbornMusic.welcome")
    log.info(
        "leave_legacy FIRED in chat=%s, user=%s",
        message.chat.id if message.chat else None,
        message.left_chat_member.id if message.left_chat_member else None,
    )
    if not departure_enabled(message.chat.id):
        log.info("leave_legacy: departure DISABLED for chat=%s — skipping", message.chat.id)
        return
    user = message.left_chat_member
    if not user or user.is_bot:
        return
    if _is_assistant(user.id):
        log.info("leave_legacy: user %s is the assistant — skipping", user.id)
        return
    if _event_seen_recently(message.chat.id, user.id, "leave"):
        log.info("leave_legacy: dedup hit for user=%s — already handled", user.id)
        return
    if await _is_chat_owner_or_admin(client, message.chat.id, user.id):
        log.info("leave_legacy: user %s is owner/admin — skipping", user.id)
        return
    try:
        await _send_leave(client, message.chat.id, user)
        log.info("leave_legacy: farewell sent chat=%s user=%s", message.chat.id, user.id)
    except Exception:
        log.exception("leave_legacy: _send_leave raised")


import logging as _logging
import time as _time

_chat_member_log = _logging.getLogger("WarbornMusic.welcome")

# Per-(chat,user,kind) dedup so the five overlapping delivery paths
# (legacy service-message, bot ChatMemberUpdated, bot raw bridge,
# userbot raw bridge, participant polling) don't send 5 welcome cards
# for one join. Insertion order = monotonic time; entries older than
# _DEDUP_TTL_S expire lazily on next check.
# INVARIANT: must comfortably exceed _POLL_INTERVAL_S plus the poll
# loop's worst per-cycle processing time. The poll path re-discovers a
# join up to one full cycle after a real-time path already handled it;
# an expired entry here means a duplicate card. (Was 30s vs a 45s poll
# interval — duplicated any join landing >30s before the next tick.)
# Cost of the larger window: a user who leaves and rejoins within 3
# minutes gets one card, not two.
_event_dedup: "dict[tuple[int, int, str], float]" = {}
_DEDUP_TTL_S = 180.0


def _is_assistant(user_id: int) -> bool:
    """True when user_id is the assistant userbot's account. The
    assistant is a regular USER (is_bot=False), so it slips past every
    is_bot check — without this filter it gets a welcome card each time
    /play auto-invites it and a farewell roast each time end_session()
    makes it leave. userbot.me is populated by pyrogram at .start();
    before that (or if the lookup fails) we filter nothing.
    """
    try:
        from bot.client import userbot
        me = getattr(userbot, "me", None)
        return me is not None and user_id == me.id
    except Exception:
        return False


def _event_seen_recently(chat_id: int, user_id: int, kind: str) -> bool:
    now = _time.monotonic()
    # Lazy expiry
    if _event_dedup:
        stale = [k for k, t in _event_dedup.items() if now - t > _DEDUP_TTL_S]
        for k in stale:
            _event_dedup.pop(k, None)
    key = (chat_id, user_id, kind)
    if key in _event_dedup and now - _event_dedup[key] < _DEDUP_TTL_S:
        return True
    _event_dedup[key] = now
    return False


async def handle_chat_member_event(bot_client, chat_member_updated, source: str = "?"):
    """Core join/leave dispatcher.

    Called from two places:
      1. The @Client.on_chat_member_updated() decorator below — bot-side,
         fires for the subset of events Telegram delivers to the bot account.
      2. bot/start.py registers this against the userbot programmatically,
         catching events Telegram doesn't reliably push to bots even when
         the bot is admin (pyrofork 2.3.69 has had spotty
         UpdateChannelParticipant delivery to bot accounts).

    `bot_client` is always the BOT client — that's what actually posts the
    welcome card / farewell roast. Even when the event came in via the
    userbot, we send the visible message via the bot.
    """
    _chat_member_log.info(
        "chat_member_updated source=%s chat=%s new_status=%s old_status=%s user=%s",
        source,
        chat_member_updated.chat.id if chat_member_updated.chat else None,
        chat_member_updated.new_chat_member.status if chat_member_updated.new_chat_member else None,
        chat_member_updated.old_chat_member.status if chat_member_updated.old_chat_member else None,
        chat_member_updated.new_chat_member.user.id if (chat_member_updated.new_chat_member and chat_member_updated.new_chat_member.user) else None,
    )
    if chat_member_updated.chat is None:
        return
    new_member = chat_member_updated.new_chat_member
    old_member = chat_member_updated.old_chat_member
    if not new_member or not new_member.user or new_member.user.is_bot:
        return
    if _is_assistant(new_member.user.id):
        _chat_member_log.info(
            "user %s is the assistant userbot — skipping (source=%s)",
            new_member.user.id, source,
        )
        return
    chat_id = chat_member_updated.chat.id
    old_status = old_member.status if old_member else ChatMemberStatus.LEFT
    if old_status in _JOIN_FROM and new_member.status in _JOIN_TO:
        _chat_member_log.info("classification=JOIN chat=%s user=%s source=%s", chat_id, new_member.user.id, source)
        if _event_seen_recently(chat_id, new_member.user.id, "join"):
            _chat_member_log.info("JOIN dedup hit (already handled within %ss) — skipping", _DEDUP_TTL_S)
            return
        if not is_enabled(chat_id):
            _chat_member_log.info("JOIN skipped: greetings.is_enabled(%s)=False", chat_id)
            return
        if new_member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
            _chat_member_log.info("JOIN skipped: new status is %s (owner/admin)", new_member.status)
            return
        _chat_member_log.info("JOIN sending welcome card to chat=%s for user=%s", chat_id, new_member.user.id)
        try:
            await _send_card(bot_client, chat_id, new_member.user)
            _chat_member_log.info("JOIN card sent ok")
        except Exception:
            _chat_member_log.exception("JOIN _send_card raised")
        return
    if old_status in _LEAVE_FROM and new_member.status in _LEAVE_TO:
        _chat_member_log.info("classification=LEAVE chat=%s user=%s source=%s", chat_id, new_member.user.id, source)
        if _event_seen_recently(chat_id, new_member.user.id, "leave"):
            _chat_member_log.info("LEAVE dedup hit (already handled within %ss) — skipping", _DEDUP_TTL_S)
            return
        if not departure_enabled(chat_id):
            _chat_member_log.info("LEAVE skipped: departure.is_enabled(%s)=False", chat_id)
            return
        if old_status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
            _chat_member_log.info("LEAVE skipped: old status was %s (owner/admin)", old_status)
            return
        _chat_member_log.info("LEAVE sending farewell to chat=%s for user=%s", chat_id, new_member.user.id)
        try:
            await _send_leave(bot_client, chat_id, new_member.user)
            _chat_member_log.info("LEAVE farewell sent ok")
        except Exception:
            _chat_member_log.exception("LEAVE _send_leave raised")
        return
    _chat_member_log.info(
        "no classification: old=%s new=%s — not a join or leave transition we care about",
        old_status, new_member.status,
    )


@Client.on_chat_member_updated()
async def welcome_via_chat_member(client, chat_member_updated):
    """Bot-side ChatMemberUpdated. Pyrofork 2.x has dropped these silently
    in some setups; the on_raw_update path below catches the underlying
    UpdateChannelParticipant directly as a belt-and-braces fallback.
    """
    _chat_member_log.info(
        "welcome_via_chat_member (BOT-side ChatMemberUpdated) FIRED in chat=%s",
        chat_member_updated.chat.id if chat_member_updated.chat else None,
    )
    from bot.client import app
    await handle_chat_member_event(app, chat_member_updated, source="bot")


# Always-on raw participant update bridge.
# Pyrofork's ChatMemberUpdatedHandler can silently drop the parsed
# ChatMemberUpdated event in 2.x — observed in our logs (loaded but
# never fires even for admin bots). UpdateChannelParticipant /
# UpdateChatParticipant arrive on the raw stream regardless, so we
# parse them ourselves and dispatch to the same handle_chat_member_event
# logic the rest of the file uses.
def _participant_status(p) -> ChatMemberStatus:
    if p is None:
        return ChatMemberStatus.LEFT
    name = type(p).__name__
    # Common pyrogram raw types: ChannelParticipant, ChannelParticipantSelf,
    # ChannelParticipantCreator, ChannelParticipantAdmin,
    # ChannelParticipantBanned, ChannelParticipantLeft,
    # ChatParticipant, ChatParticipantCreator, ChatParticipantAdmin
    if "Left" in name:
        return ChatMemberStatus.LEFT
    if "Banned" in name or "Kicked" in name:
        return ChatMemberStatus.BANNED
    if "Creator" in name:
        return ChatMemberStatus.OWNER
    if "Admin" in name:
        return ChatMemberStatus.ADMINISTRATOR
    return ChatMemberStatus.MEMBER


def _participant_user_id(p) -> int | None:
    if p is None:
        return None
    for attr in ("user_id", "peer"):
        v = getattr(p, attr, None)
        if v is None:
            continue
        if isinstance(v, int):
            return v
        uid = getattr(v, "user_id", None)
        if isinstance(uid, int):
            return uid
    return None


_RAW_TYPE_COUNTS: dict[str, int] = {}


# Intentionally NOT decorated with @Client.on_raw_update() — pyrofork's
# plugin loader adds raw handlers to group=0, where they're starved by
# parsed handlers earlier in the iteration (first matching handler in
# the group fires + breaks). bot/start.py registers this function in
# its own group=-9999 via app.add_handler so it fires for every update.
_POLL_INTERVAL_S = 45
_member_snapshot: dict[int, set[int]] = {}
_poll_log = _logging.getLogger("WarbornMusic.welcome.poll")


async def _list_chats_to_poll(client_app) -> list[int]:
    """Read the chat registry the broadcast plugin maintains. all_chats
    is sync but cheap (in-memory list).
    """
    try:
        from bot.utils.chats import all_chats
        return [c for c in all_chats() if c < 0]
    except Exception:
        _poll_log.exception("could not load chat registry; polling disabled this cycle")
        return []


# Skip polling chats above this member count. get_chat_members pages at
# 200/request, so a 10k-member group would cost ~50 API calls per 45s
# cycle — a FloodWait factory. Real-time paths (raw bridge, legacy
# service messages) still cover big groups; only the polling fallback is
# skipped. Override with WELCOME_POLL_MAX_MEMBERS.
import os as _os
_POLL_MAX_MEMBERS = int(_os.getenv("WELCOME_POLL_MAX_MEMBERS", "1000"))
_poll_skipped_big: set[int] = set()  # warn once per chat, not per cycle


async def _snapshot_members(client_app, chat_id: int) -> set[int] | None:
    """Return a set of human member ids in chat_id, or None on error.
    Bots are filtered. Requires bot to be admin with member-list rights.
    Chats above _POLL_MAX_MEMBERS are skipped (returns None).
    """
    members: set[int] = set()
    try:
        count = await client_app.get_chat_members_count(chat_id)
        if count > _POLL_MAX_MEMBERS:
            if chat_id not in _poll_skipped_big:
                _poll_skipped_big.add(chat_id)
                _poll_log.warning(
                    "chat=%s has %d members > WELCOME_POLL_MAX_MEMBERS=%d — "
                    "polling fallback disabled for this chat (real-time "
                    "paths still active)",
                    chat_id, count, _POLL_MAX_MEMBERS,
                )
            return None
        async for m in client_app.get_chat_members(chat_id):
            user = getattr(m, "user", None)
            if user is None or getattr(user, "is_bot", False):
                continue
            uid = getattr(user, "id", None)
            if uid is not None:
                members.add(uid)
        return members
    except Exception as exc:
        _poll_log.info("snapshot failed for chat=%s: %s", chat_id, exc)
        return None


async def _fire_join_poll(client_app, chat_id: int, user_id: int) -> None:
    """Build a synthetic ChatMemberUpdated and dispatch via the same
    handle_chat_member_event used by every other delivery path.
    """
    try:
        user_obj = await client_app.get_users(user_id)
    except Exception:
        return
    if user_obj is None or getattr(user_obj, "is_bot", False):
        return
    try:
        chat_obj = await client_app.get_chat(chat_id)
    except Exception:
        class _C: pass
        chat_obj = _C(); chat_obj.id = chat_id

    class _M: pass
    om = _M(); om.status = ChatMemberStatus.LEFT; om.user = user_obj
    nm = _M(); nm.status = ChatMemberStatus.MEMBER; nm.user = user_obj
    class _E: pass
    e = _E(); e.chat = chat_obj; e.old_chat_member = om; e.new_chat_member = nm
    await handle_chat_member_event(client_app, e, source="poll")


async def _fire_leave_poll(client_app, chat_id: int, user_id: int) -> None:
    try:
        user_obj = await client_app.get_users(user_id)
    except Exception:
        return
    if user_obj is None or getattr(user_obj, "is_bot", False):
        return
    try:
        chat_obj = await client_app.get_chat(chat_id)
    except Exception:
        class _C: pass
        chat_obj = _C(); chat_obj.id = chat_id

    class _M: pass
    om = _M(); om.status = ChatMemberStatus.MEMBER; om.user = user_obj
    nm = _M(); nm.status = ChatMemberStatus.LEFT; nm.user = user_obj
    class _E: pass
    e = _E(); e.chat = chat_obj; e.old_chat_member = om; e.new_chat_member = nm
    await handle_chat_member_event(client_app, e, source="poll")


async def poll_participants_forever(client_app) -> None:
    """Per-chat membership snapshot loop. First pass establishes the
    baseline (no events fired). Subsequent passes diff against the
    previous snapshot and fire welcomes/farewells for new/missing ids.
    Failures per chat are caught individually — one bad chat doesn't
    stall the rest. Interval gated by _POLL_INTERVAL_S.
    """
    import asyncio as _a
    while True:
        try:
            chats = await _list_chats_to_poll(client_app)
            for cid in chats:
                snap = await _snapshot_members(client_app, cid)
                if snap is None:
                    continue
                prev = _member_snapshot.get(cid)
                _member_snapshot[cid] = snap
                if prev is None:
                    _poll_log.info("baseline established chat=%s members=%d", cid, len(snap))
                    continue
                joined = snap - prev
                left = prev - snap
                if joined or left:
                    _poll_log.info("poll chat=%s joined=%d left=%d", cid, len(joined), len(left))
                for uid in joined:
                    try:
                        await _fire_join_poll(client_app, cid, uid)
                    except Exception:
                        _poll_log.exception("poll join dispatch failed")
                for uid in left:
                    try:
                        await _fire_leave_poll(client_app, cid, uid)
                    except Exception:
                        _poll_log.exception("poll leave dispatch failed")
        except Exception:
            _poll_log.exception("polling loop iteration crashed")
        await _a.sleep(_POLL_INTERVAL_S)


async def _raw_participant_bridge(client, update, users, chats):
    cls = type(update).__name__
    # Debug: count + occasionally dump every update type the bot
    # actually receives, so 'why isn't the participant event firing'
    # is answerable from the log.
    _RAW_TYPE_COUNTS[cls] = _RAW_TYPE_COUNTS.get(cls, 0) + 1
    if _RAW_TYPE_COUNTS[cls] in (1, 10, 100, 1000):
        _chat_member_log.info(
            "raw_update seen: cls=%s count=%d (cumulative type histogram: %s)",
            cls, _RAW_TYPE_COUNTS[cls],
            ", ".join(f"{k}={v}" for k, v in sorted(_RAW_TYPE_COUNTS.items(), key=lambda kv: -kv[1])[:12]),
        )
    if cls not in ("UpdateChannelParticipant", "UpdateChatParticipant"):
        return
    try:
        prev = getattr(update, "prev_participant", None)
        new = getattr(update, "new_participant", None)
        old_status = _participant_status(prev)
        new_status = _participant_status(new)

        # Determine which chat_id (-100... for channels, negative int for chats)
        if cls == "UpdateChannelParticipant":
            channel_id = update.channel_id
            chat_id = int(f"-100{channel_id}")
        else:
            chat_id = -update.chat_id

        # Pyrofork ChatMemberStatus checks against MEMBER/RESTRICTED for new
        # status when joining. Our existing _JOIN_FROM/_LEAVE_FROM tuples
        # use the same enum so we can drive `handle_chat_member_event`
        # logic with a stub object that exposes .chat, .new_chat_member,
        # .old_chat_member with .status / .user (.id, .is_bot, .first_name…).
        user_id = _participant_user_id(new) or _participant_user_id(prev)
        if user_id is None:
            return
        # Filter bot self-events: skip if user_id matches our own bot id
        try:
            me = await client.get_me()
            if me and user_id == me.id:
                return
        except Exception:
            pass

        # Resolve a User object so the welcome card / farewell can name them.
        try:
            user_obj = await client.get_users(user_id)
        except Exception:
            user_obj = None
        if user_obj is None or getattr(user_obj, "is_bot", False):
            return

        # Resolve Chat for chat_member_updated.chat.id semantics.
        try:
            chat_obj = await client.get_chat(chat_id)
        except Exception:
            class _C:
                pass
            chat_obj = _C()
            chat_obj.id = chat_id

        class _Member:
            pass

        old_m = _Member(); old_m.status = old_status; old_m.user = user_obj
        new_m = _Member(); new_m.status = new_status; new_m.user = user_obj

        class _Evt:
            pass
        evt = _Evt()
        evt.chat = chat_obj
        evt.old_chat_member = old_m
        evt.new_chat_member = new_m

        _chat_member_log.info(
            "raw_participant_bridge: %s chat=%s user=%s old=%s new=%s",
            cls, chat_id, user_id, old_status, new_status,
        )
        await handle_chat_member_event(client, evt, source="raw")
    except Exception:
        _chat_member_log.exception("raw_participant_bridge crashed for %s", cls)
