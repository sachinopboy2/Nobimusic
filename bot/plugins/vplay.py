from pyrogram import Client, filters

from bot.utils.play_actions import do_play


@Client.on_message(filters.command(["vplay", "cplay"]))
async def vplay_command(client, message):
    await do_play(client, message, is_video=True)
