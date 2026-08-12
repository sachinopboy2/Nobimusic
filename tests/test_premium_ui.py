"""Static regression checks for premium custom-emoji UI."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
start=(ROOT/"bot/plugins/start.py").read_text()
help_py=(ROOT/"bot/plugins/help.py").read_text()
emoji=(ROOT/"bot/utils/emoji.py").read_text()

for name in ["NOTE_ID","MUSIC_ID","BOLT_ID","FIRE_ID","BRAIN_ID","PEOPLE_ID",
             "HEAD_ID","USER_ID","IDCARD_ID","MEGA_ID","CHAT_ID","CROWN_ID",
             "PLUS_ID","BOOK_ID"]:
    assert name in emoji, f"missing centralized ID: {name}"

for name in ["e.NOTE","e.MUSIC","e.BOLT","e.FIRE","e.BRAIN",
             "e.PEOPLE","e.HEAD","e.USER","e.IDCARD"]:
    assert name in start, f"/start missing {name}"

for name in ["e.MUSIC","e.SHIELD","e.WAVE","e.IDCARD","e.GEAR",
             "e.DICE","e.CROWN","e.NOTE"]:
    assert name in help_py, f"/help missing {name}"

assert "icon_custom_emoji_id" in start
assert "ButtonStyle.PRIMARY" in start
assert "ButtonStyle.SUCCESS" in start
assert '<emoji id="' not in start
assert '<emoji id="' not in help_py
print("PASS: premium custom-emoji UI regression checks")
