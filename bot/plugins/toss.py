import secrets

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from bot.utils import emoji as e

_HEAD = f"{e.DICE} <b>Coin Toss</b>"


@Client.on_message(filters.command("toss"))
async def toss_command(client, message):
    side = "Heads" if secrets.randbelow(2) == 0 else "Tails"  # the flip

    # No prediction → existing behaviour, output unchanged.
    if len(message.command) < 2:
        await message.reply_text(
            f"{_HEAD}\n━━━━━━━━━━━\n🪙 <b>{side}!</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    choice = message.command[1].strip().lower()
    if choice not in ("heads", "tails"):
        await message.reply_text("«Please choose either heads or tails.»")
        return

    pick = choice.capitalize()
    if pick == side:
        body = (
            f"{e.FIRE} <b>Congratulations!</b> Your prediction was correct.\n"
            "Luck is on your side today!"
        )
    else:
        body = (
            "😔 <b>Better luck next time!</b>\n"
            "The coin had other plans this round."
        )
    await message.reply_text(
        f"{_HEAD}\n\n"
        f"<b>Your Choice:</b> {pick}\n"
        f"<b>Result:</b> {side}\n\n"
        f"{body}",
        parse_mode=ParseMode.HTML,
    )
