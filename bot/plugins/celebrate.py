"""/celebrate <occasion> — celebratory shout-outs for a replied user.

Structural conventions mirror bot/plugins/pat.py and kill.py: target
resolution via reply / text-mention / @username / user_id, premium
emoji via <emoji id="..."> tags, graceful text fallback.

Two enhancements over a static reply:
  • Telegram message effect (confetti) when the installed pyrofork
    supports message_effect_id — attempted with a graceful fallback
    to no-effect if the effect id is rejected.
  • Optional trailing `loud` arg → pin the celebration (needs the
    bot's own can_pin_messages privilege; silently skipped otherwise,
    since it's a bonus the admin didn't explicitly request via /pin).
"""

import inspect
import logging

from pyrogram import Client, filters
from pyrogram.enums import ChatMemberStatus, MessageEntityType, ParseMode

logger = logging.getLogger("WarbornMusic.celebrate")

# Telegram free message-effect ids (tied to standard reaction emoji).
# Community-sourced and NOT officially documented — so every send that
# uses one is wrapped to fall back to no-effect if Telegram rejects it.
# 🎉 confetti / party popper:
_EFFECT_CONFETTI = 5046509860389126442

# Whether the running pyrofork build accepts message_effect_id at all.
_EFFECT_SUPPORTED = "message_effect_id" in inspect.signature(
    Client.send_message
).parameters
_warned_no_effect = False


# occasion key → (emoji_ids, template). {a} = announcer, {t} = target.
_OCCASIONS = {
    "birthday": (
        ["5386414139130260061"],
        "{e0} {a} just announced it's {t}'s birthday! 🎂🎉\n\n"
        "Another trip around the sun, survived with style. "
        "Cake protocol initiated.",
    ),
    "anniversary": (
        ["5386414139130260061"],
        "{e0} {a} is celebrating {t}'s anniversary! 🎉\n\n"
        "Time flies, the legend remains. Here's to many more.",
    ),
    "promotion": (
        ["5386414139130260061"],
        "{e0} {a} congratulates {t} on the promotion! 🏆\n\n"
        "Earned, not given. The grind paid off — take the W.",
    ),
    "win": (
        ["5386414139130260061"],
        "{e0} {a} salutes {t} for the win! 🏅\n\n"
        "Victory tastes better when it's deserved. Absolute legend.",
    ),
    "welcome-back": (
        ["5460858729962421671"],
        "{e0} {a} welcomes {t} back! 👋\n\n"
        "The chat wasn't the same without you. Good to have you home.",
    ),
}

# alias → canonical occasion key.
_ALIASES = {
    "bday": "birthday", "birthday": "birthday", "hbd": "birthday",
    "anniversary": "anniversary", "anni": "anniversary",
    "promotion": "promotion", "promo": "promotion",
    "win": "win", "victory": "win", "won": "win",
    "welcome-back": "welcome-back", "wb": "welcome-back", "welcomeback": "welcome-back",
}

_FALLBACK = "🎉"
_USAGE = (
    "🎊 Usage: /celebrate <occasion> (reply to a user)\n"
    "Supported: bday, anniversary, promotion, win, welcome-back\n"
    "Add `loud` to pin it, e.g. /celebrate bday loud"
)

_ADMIN_STATUSES = (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)


async def _resolve_target(client, message):
    """(user, mention_html) or (None, None) — reply / text-mention / @ / id."""
    for ent in (message.entities or []):
        if ent.type == MessageEntityType.TEXT_MENTION and ent.user:
            return ent.user, ent.user.mention
    reply = message.reply_to_message
    if reply and reply.from_user:
        return reply.from_user, reply.from_user.mention
    # /celebrate <occasion> <@username|id>
    if len(message.command) >= 3:
        raw = message.command[2].lstrip("@")
        from bot.client import userbot
        try:
            if raw.isdigit():
                u = await client.get_users(int(raw))
            else:
                try:
                    u = await userbot.get_users(raw)
                except Exception:
                    u = await client.get_users(raw)
            return u, u.mention
        except Exception:
            if raw.isdigit():
                return None, f'<a href="tg://user?id={raw}">user {raw}</a>'
    return None, None


def _announcer_mention(message) -> str:
    u = message.from_user
    if not u:
        return "someone"
    return u.mention or (u.first_name or str(u.id))


def _render(template: str, emoji_ids: list[str], announcer: str, target: str) -> str:
    tags = {f"e{i}": f'<emoji id="{eid}">{_FALLBACK}</emoji>' for i, eid in enumerate(emoji_ids)}
    return template.format(a=announcer, t=target, **tags)


async def _bot_can_pin(client, chat_id) -> bool:
    try:
        me = await client.get_me()
        member = await client.get_chat_member(chat_id, me.id)
    except Exception:
        return False
    if member.status == ChatMemberStatus.OWNER:
        return True
    privs = getattr(member, "privileges", None)
    return bool(privs and getattr(privs, "can_pin_messages", False))


@Client.on_message(filters.command("celebrate"))
async def celebrate_command(client, message):
    global _warned_no_effect

    args = message.command[1:]
    # First non-"loud" arg is the occasion.
    occasion_arg = None
    loud = False
    for a in args:
        if a.lower() in ("loud", "notify"):
            loud = True
        elif occasion_arg is None:
            occasion_arg = a.lower()

    if not occasion_arg:
        await message.reply_text(_USAGE)
        return

    key = _ALIASES.get(occasion_arg)
    if key is None:
        await message.reply_text(
            f"🎊 Unknown occasion '{occasion_arg}'.\n" + _USAGE
        )
        return

    target, target_mention = await _resolve_target(client, message)
    if target_mention is None:
        await message.reply_text(_USAGE)
        return

    announcer = _announcer_mention(message)
    emoji_ids, template = _OCCASIONS[key]
    text = _render(template, emoji_ids, announcer, target_mention)

    # Send, attempting the confetti effect first when supported.
    sent = None
    send_kwargs = dict(
        chat_id=message.chat.id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_to_message_id=message.id,
        disable_web_page_preview=True,
    )
    if _EFFECT_SUPPORTED:
        try:
            sent = await client.send_message(message_effect_id=_EFFECT_CONFETTI, **send_kwargs)
        except Exception as exc:
            logger.info("celebrate: effect send rejected (%s), retrying plain", type(exc).__name__)
    else:
        if not _warned_no_effect:
            logger.warning("celebrate: pyrofork build has no message_effect_id support — sending without effects")
            _warned_no_effect = True

    if sent is None:
        try:
            sent = await client.send_message(**send_kwargs)
        except Exception:
            logger.exception("celebrate: send failed")
            return

    # Optional auto-pin (bonus — never errors out the command).
    if loud and sent is not None:
        if await _bot_can_pin(client, message.chat.id):
            try:
                await client.pin_chat_message(
                    chat_id=message.chat.id,
                    message_id=sent.id,
                    disable_notification=False,
                )
            except Exception:
                logger.info("celebrate: pin failed (ignored)")
        else:
            logger.info("celebrate: loud requested but bot lacks pin rights — skipping pin")
