from pyrogram import Client, filters

from bot.utils.play_actions import do_skip


@Client.on_message(filters.command("skip"))
async def skip_command(client, message):
    await do_skip(client, message)
