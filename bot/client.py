from pyrogram import Client
from bot.config import API_ID, API_HASH, BOT_TOKEN, PROXY, STRING_SESSION

# Pyrofork accepts proxy=None to mean "direct" but recent pyrofork
# versions reject the kwarg being None — pass it only if set.
_proxy_kwargs = {"proxy": PROXY} if PROXY else {}

# IMPORTANT: `plugins=dict(root="bot.plugins")` is what actually binds the
# @Client.on_message decorators in bot/plugins/*.py to this client. Without
# it pyrofork stores the handler metadata on the function but never calls
# add_handler — meaning the bot logs in but answers nothing.
app = Client(
    "WarbornMusic",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="bot.plugins"),
    **_proxy_kwargs,
)

userbot = Client(
    "WarbornMusicAssistant",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=STRING_SESSION,
    **_proxy_kwargs,
)
