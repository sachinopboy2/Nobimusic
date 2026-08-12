import asyncio

from pyrogram import idle

from bot.client import app, userbot
from bot.logger import logger
from bot.utils import music as music_mod
from bot.utils import playback as playback_mod

# Strong reference to the participant polling task (see _run); asyncio
# keeps only weak refs to tasks, so this must live at module scope.
_poll_task: "asyncio.Task | None" = None
_autodelete_task: "asyncio.Task | None" = None
_cookie_task: "asyncio.Task | None" = None


def _rebind_pyrofork_loops() -> None:
    """Repair pyrofork's import-time loop capture.

    Pyrofork's Dispatcher.__init__ calls asyncio.get_event_loop() at module
    import time. On Python 3.10+ that returns a separate loop from the one
    asyncio.run() creates at runtime — so handler-worker tasks get scheduled
    on a dead loop and never execute. Pointing dispatcher.loop at the
    current running loop before any client.start() call fixes this.
    """
    loop = asyncio.get_running_loop()
    for client in (app, userbot):
        client.dispatcher.loop = loop


async def _stage(name: str, coro):
    """Run a startup coroutine, log the stage that failed before re-raising.

    Bare tracebacks from a failed `userbot.start()` look identical to a
    failed `app.start()` in journalctl — both show a Telegram client
    error with no hint at which client. Wrapping each step in a named
    stage tag makes the failure point obvious without changing behaviour.
    """
    try:
        return await coro
    except Exception:
        logger.exception("Startup failed at stage: %s", name)
        raise


async def _start_userbot_resilient(attempts: int = 4, backoff: int = 15):
    """Start the userbot, riding out a deploy-overlap collision.

    If the previous instance is still shutting down, our connect can hit
    AUTH_KEY_DUPLICATED. Retry a few times with backoff so that once the old
    instance is gone the session connects cleanly — avoiding a crash-loop
    (and, when the collision is only transient, avoiding a dead session).
    """
    from pyrogram.errors import AuthKeyDuplicated

    for i in range(attempts):
        try:
            await userbot.start()
            return
        except AuthKeyDuplicated:
            if i == attempts - 1:
                raise
            logger.warning(
                "userbot AUTH_KEY_DUPLICATED (attempt %d/%d) — another instance "
                "is likely still shutting down; retrying in %ss",
                i + 1, attempts, backoff,
            )
            await asyncio.sleep(backoff)


async def _run():
    # Step 1 — fix pyrofork's loop capture so handlers fire.
    _rebind_pyrofork_loops()

    # Step 2 — construct PyTgCalls inside the running loop. This is the
    # equivalent rebind for py-tgcalls; instead of patching every internal
    # asyncio primitive (loop, ChatLock, Cache, NTgCalls callbacks) we just
    # build the instance after the loop exists. Then register the
    # stream-end auto-advance handler against it.
    music_mod.init(userbot)
    playback_mod.register_handlers()

    # Pyrofork loads bot/plugins/*.py automatically on app.start() because
    # bot/client.py passes plugins=dict(root="bot.plugins"). By the time
    # plugin imports happen, music_mod.music is populated — plugins that
    # do `from bot.utils.music import music` will name-bind the live
    # instance correctly.
    logger.info("Starting Warborn Music")

    # Deploy-overlap guard. Railway (and most PaaS) do ROLLING deploys: the
    # OLD instance keeps running for a few seconds while the NEW one boots.
    # For that window two processes share one MTProto userbot session →
    # Telegram fires AUTH_KEY_DUPLICATED and permanently kills the session,
    # so the new instance then crash-loops. Wait for the old instance to be
    # torn down before connecting the userbot, and retry across the overlap.
    import os as _os
    _delay = int(_os.getenv("USERBOT_START_DELAY", "25"))
    if _delay > 0:
        logger.info("Deploy-overlap guard: waiting %ss for any old instance "
                    "to shut down before connecting the userbot…", _delay)
        await asyncio.sleep(_delay)
    await _stage("userbot.start", _start_userbot_resilient())
    await _stage("music.start", music_mod.music.start())
    await _stage("app.start (bot + plugin load)", app.start())

    # Auto-delete the bot's group/channel responses after a delay (DMs
    # excluded). Wrap send methods now so every subsequent send is covered.
    from bot.utils import autodelete
    autodelete.install(app)
    global _autodelete_task
    _autodelete_task = asyncio.create_task(autodelete.run_sweeper(app))
    _autodelete_task.add_done_callback(
        lambda t: logger.error(
            "autodelete sweeper EXITED unexpectedly: %r",
            t.exception() if not t.cancelled() else "cancelled",
        )
    )

    # Persistence mode banner — makes an unset/unreachable REDIS_URL obvious in
    # the Railway logs (otherwise the fallback to ephemeral JSON is silent).
    try:
        from bot.utils import kvstore
        logger.warning(kvstore.startup_status())
    except Exception:
        logger.exception("kvstore status check failed (continuing)")

    # Automatic YouTube cookie management: discover the supplied jars and run
    # the background health monitor / intelligent rotation. Non-blocking; if no
    # jars are configured it idles and yt-dlp simply runs cookieless.
    from bot.utils import cookie_manager
    try:
        cookie_manager.init()
    except Exception:
        logger.exception("cookie_manager.init failed (continuing cookieless)")
    global _cookie_task
    _cookie_task = asyncio.create_task(cookie_manager.run_forever())
    _cookie_task.add_done_callback(
        lambda t: logger.error(
            "cookie health monitor EXITED unexpectedly: %r",
            t.exception() if not t.cancelled() else "cancelled",
        )
    )

    # Instance fingerprint — posted RIGHT AFTER the bot comes online, BEFORE
    # the userbot post-start steps (which crash a duplicate instance on
    # AUTH_KEY_DUPLICATED). A duplicate that comes online will reply to
    # commands and fire the health monitor but may die before the end of
    # startup — so the card must post here to reveal EVERY live process.
    # Two cards with different ids at once = duplicate instances running;
    # the differing ip is the rogue host to kill.
    import uuid as _uuid
    _boot_id = _uuid.uuid4().hex[:8]
    _public_ip = "?"
    try:
        import aiohttp as _aiohttp
        async with _aiohttp.ClientSession(
            timeout=_aiohttp.ClientTimeout(total=5)
        ) as _s:
            async with _s.get("https://api.ipify.org") as _r:
                _public_ip = (await _r.text()).strip() or "?"
    except Exception:
        pass
    logger.warning(
        "INSTANCE BOOT id=%s ip=%s — two different ids live at once = "
        "DUPLICATE instances.", _boot_id, _public_ip,
    )
    try:
        from bot.utils.logchannel import send_log as _send_log
        await _send_log(
            app,
            "🟢 <b>INSTANCE BOOT</b>\n"
            f"id: <code>{_boot_id}</code>\n"
            f"ip: <code>{_public_ip}</code>\n\n"
            "⚠️ More than one of these with different <b>id</b>s = duplicate "
            "instances running. Kill all but one (the differing ip is the culprit)."
        )
    except Exception:
        logger.exception("boot fingerprint log failed")

    # Backfill the /broadcast chat registry from the userbot's perspective.
    from bot.utils.discover import backfill_common_chats
    try:
        await backfill_common_chats()
    except Exception:
        logger.exception("backfill_common_chats failed (continuing)")

    # Subscribe the userbot to ChatMemberUpdated. This is the always-on
    # path for greetings + departures. Telegram's MTProto only delivers
    # UpdateChannelParticipant to bot accounts under specific scope
    # conditions, and pyrofork 2.3.69 has had inconsistent behaviour
    # there. The userbot is a regular user — it gets these unconditionally
    # for every chat it's in.
    from pyrogram.handlers import ChatMemberUpdatedHandler, RawUpdateHandler
    from bot.plugins.welcome import (
        handle_chat_member_event,
        _raw_participant_bridge,
    )

    async def _userbot_member_dispatch(_client, chat_member_updated):
        try:
            await handle_chat_member_event(app, chat_member_updated, source="userbot")
        except Exception:
            logger.exception("userbot chat_member_updated dispatch failed")

    userbot.add_handler(ChatMemberUpdatedHandler(_userbot_member_dispatch))

    # Same raw participant bridge that's registered on the bot, attached
    # to the userbot too.
    async def _userbot_raw_bridge(_client, update, users, chats):
        try:
            await _raw_participant_bridge(app, update, users, chats)
        except Exception:
            logger.exception("userbot raw participant bridge failed")

    userbot.add_handler(RawUpdateHandler(_userbot_raw_bridge))

    # ALSO register the bridge on the BOT client programmatically.
    # pyrofork 2.2.21 plugin-scanner loads RawUpdateHandler decorators
    # ("[LOAD] RawUpdateHandler ... in group 0") but the Dispatcher does
    # not invoke them at runtime — verified empirically. Explicit
    # add_handler bypasses the broken plugin path.
    async def _app_raw_bridge(_client, update, users, chats):
        try:
            await _raw_participant_bridge(app, update, users, chats)
        except Exception:
            logger.exception("bot raw participant bridge failed")

    app.add_handler(RawUpdateHandler(_app_raw_bridge), group=-9999)
    logger.info("Registered userbot + bot ChatMemberUpdated dispatch + raw bridge (programmatic)")

    # Polling fallback. Telegram MTProto stops pushing
    # UpdateChannelParticipant to bot accounts in some scopes — verified
    # empirically: bot is admin everywhere with full rights yet zero
    # participant updates arrive even while message updates flow normally.
    # Periodically snapshot membership and fire join/leave for diffs so
    # greetings/departures work regardless of update delivery.
    from bot.plugins.welcome import poll_participants_forever
    # Keep a strong reference — asyncio only holds a weak ref to tasks,
    # so an unreferenced create_task() can be garbage-collected and the
    # polling loop silently stops. The done-callback makes an unexpected
    # exit visible in the log (the loop is meant to run forever).
    global _poll_task
    _poll_task = asyncio.create_task(poll_participants_forever(app))
    _poll_task.add_done_callback(
        lambda t: logger.error(
            "participant polling loop EXITED unexpectedly: %r",
            t.exception() if not t.cancelled() else "cancelled",
        )
    )
    logger.info("Started participant polling loop")

    # Diagnostic: dump the groups dict on both dispatchers so we can
    # confirm RawUpdateHandler is actually in the runtime handler list.
    for label, cli in (("bot", app), ("userbot", userbot)):
        try:
            groups = cli.dispatcher.groups
            summary = []
            for grp, hs in groups.items():
                summary.append(f"g{grp}=" + ",".join(type(h).__name__ for h in hs))
            logger.info("dispatcher[%s] handler groups: %s", label, " | ".join(summary)[:1200])
        except Exception:
            logger.exception("could not dump dispatcher groups for %s", label)

    # Cookie diagnostics — a typo'd COOKIES_FILE path silently behaves
    # the same as unset, so surface the real state at boot.
    import os as _os
    for env_name, host_label in (
        ("COOKIES_FILE", "YouTube"),
        ("INSTAGRAM_COOKIES_FILE", "Instagram"),
    ):
        path = _os.getenv(env_name, "").strip()
        if not path:
            logger.warning(
                "%s is unset — %s downloads will fail on the "
                "bot-check / login wall. Set %s=/abs/path/cookies.txt in .env.",
                env_name, host_label, env_name,
            )
        elif _os.path.exists(path):
            logger.info("%s is set and exists: %s", env_name, path)
        else:
            logger.warning(
                "%s is set to %r but that path does NOT exist on disk "
                "— treated the same as unset. Check for a typo.",
                env_name, path,
            )

    # Media API: seed the endpoint registry from env, run initial health
    # check, and start the background health monitor for auto-failover.
    from bot.utils.api_registry import get_registry
    registry = get_registry()
    if registry.endpoints:
        from bot.utils.media_api_client import health_check
        try:
            ok, detail = await health_check()
            ep = registry.active
            label = ep.url if ep else "(none)"
            if ok:
                logger.info("MEDIA_API reachable at %s — %s", label, detail)
            else:
                logger.warning(
                    "MEDIA_API at %s is NOT reachable: %s — IG/Pinterest will "
                    "fall through to in-process yt-dlp.",
                    label, detail,
                )
        except Exception as exc:
            logger.warning(
                "MEDIA_API health check raised %s: %s — IG/Pinterest will "
                "fall through to in-process yt-dlp.",
                type(exc).__name__, exc,
            )
        from bot.utils.api_health import start_monitor
        start_monitor(app)
        logger.info("API health monitor started (%d endpoint(s))", len(registry.endpoints))
    else:
        from bot.config import MEDIA_API_URL
        if MEDIA_API_URL:
            from bot.utils.media_api_client import health_check
            try:
                ok, detail = await health_check()
                if ok:
                    logger.info("MEDIA_API reachable at %s — %s", MEDIA_API_URL, detail)
                else:
                    logger.warning(
                        "MEDIA_API at %s is NOT reachable: %s",
                        MEDIA_API_URL, detail,
                    )
            except Exception as exc:
                logger.warning("MEDIA_API health check raised %s: %s", type(exc).__name__, exc)

    # Empirical membership snapshot — list every chat the userbot is
    # currently a member of. Greetings/departure delivery via the userbot
    # ChatMemberUpdated path depends on the userbot being in the chat at
    # the moment a join/leave happens; this shows what it can see at boot.
    try:
        dialog_chats = []
        async for dialog in userbot.get_dialogs():
            ch = dialog.chat
            if ch and ch.type and ch.type.value in ("group", "supergroup"):
                dialog_chats.append(f"{ch.id} ({ch.title})")
        logger.info(
            "userbot is a member of %d group(s)/supergroup(s): %s",
            len(dialog_chats),
            "; ".join(dialog_chats) if dialog_chats else "(none)",
        )
    except Exception:
        logger.exception("could not enumerate userbot dialogs at startup")

    me = await app.get_me()
    logger.info(f"Logged in as @{me.username} ({me.id})")

    await idle()
    await app.stop()
    await userbot.stop()


def start_bot():
    asyncio.run(_run())
