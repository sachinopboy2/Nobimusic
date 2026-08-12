"""Savage farewells for the leave handler.

Each message contains `{name}` which gets replaced with the leaver's display
name (HTML mention, so it stays clickable). We keep a small per-chat ring buffer
of recently-used indices to avoid back-to-back repeats.
"""

import random
from collections import deque
from threading import Lock

MESSAGES = [
    "{name} has left. Finally, the liability is gone. 🗑️",
    "{name} left the chat. Group IQ just went up by 30 points. 📈",
    "{name} packed up and left. The group's collective trauma is now 12% lighter. 🫧",
    "{name} ragequit. Nobody's chasing. Don't come back. 🚪",
    "{name} left. The chat will recover within minutes. We were already pretending not to notice them. 👀",
    "{name} is gone. The vibe just got upgraded for free. ✨",
    "{name} left the group. We were saving the kick for later — they did us a favor. 🪑",
    "Lost: {name}. Reward: nothing. Description: won't be missed. 📜",
    "{name} exited. Performance reviews indicate this is an upgrade. 📋",
    "{name} ghosted the chat. Honestly the most useful thing they've done here. 👻",
    "Breaking: {name} has left. In other news, nobody cares. 📰",
    "{name} took the L and dipped. Take the hint and don't come back. ✋",
    "{name} left without saying goodbye. The audacity to think we wanted one. 💅",
    "{name} unsubscribed from the group. Wise move — we were about to charge rent. 💸",
    "{name} packed their dead weight and left. Lighter already. 🎈",
    "{name} left the chat. A net positive for the group's standardized testing scores. 🧠",
    "{name} ran for the exit so fast they left their dignity behind. We'll burn it. 🔥",
    "{name} has been removed by themselves. Best decision they've ever made. ✅",
    "{name} left. Don't take it personally — they were never personality anyway. 🤡",
    "{name} bounced. Group emotional damage reduced by 84%. 📉",
    "{name} exited stage left. Tragically without an encore. 🎭",
    "{name} clocked out permanently. Pension: declined. 🕔",
    "{name} disappeared. We had a poll going to see when. Three people guessed correctly. 🗳️",
    "{name} chose violence — against the door, on their way out. 🚪💨",
    "{name} left. The group chat just hit a personal record for collective relief. 🏆",
    "{name} pulled the plug on their group membership. Should've pulled it on the wifi instead. 🔌",
    "{name} left so dramatically Shakespeare would shed a tear. We won't. 🎭",
    "{name} is gone. Funeral arrangements: none. Attendance: none. Vibes: ascending. 🪦",
    "{name} took the express elevator out. Hope they read the maintenance notice. 🛗",
    "{name} left the chat. The remaining members got a 10% morale boost effective immediately. 📊",
    # ---- batch 2: even more savage ----
    "{name} left. Honestly we were one personality trait away from staging an intervention. 🛑",
    "{name} exited the group. Sources confirm even their reflection unfollowed them. 🪞",
    "{name} departed. Achievement unlocked: Self-Awareness (Bronze). 🏅",
    "{name} ghosted us. Their charisma did the same to them years ago. ✌️",
    "{name} left. The group hit fifteen seconds of silence before realizing it was finally peaceful. 🧘",
    "{name} packed their grievances and left. Sadly they forgot their personality on the way out. 🎒",
    "{name} bounced. Even the typing dots breathed a sigh of relief. ⌨️",
    "{name} has exited. Effective immediately, the chat's collective braincell is back in service. 🧠",
    "{name} left so hard the door bounced back twice. We added a brick to keep it shut. 🧱",
    "{name} is gone. We've already redistributed their seat to a houseplant. The plant contributes more. 🪴",
    "{name} unsubscribed. The algorithm learned a valuable lesson today. 🤖",
    "{name} left. The eulogy fit on a sticky note. We didn't write one. 🗒️",
    "{name} departed. Their group photo presence has been retroactively cropped out by popular demand. ✂️",
    "{name} chose to leave before we chose for them. Respect for the speed run. ⏱️",
    "{name} left. Honestly the only respectful thing they've ever done in here. 👏",
    "{name} disappeared. The void looked at us and said 'no thanks, you keep them — wait, you don't have to anymore. 🫥",
    "{name} left. Their last message will go unread, as a tradition we already started. 📩",
    "{name} packed up. The collective dignity of this chat just rose by triple digits. 📈",
    "{name} left the group. Even the captcha was relieved. 🤖",
    "{name} dipped. Their replies were already in airplane mode anyway. ✈️",
    "{name} exited. The group dynamic is now mathematically optimal. ➕",
    "{name} left and we're already pretending they never joined. The history books agree. 📚",
    "{name} bounced. They thought it was a flex. We're calling it a service. 💪",
    "{name} left. The wifi got 30% faster. Coincidence? Statistically, no. 📶",
    "{name} packed their issues and left. The luggage was overweight, the room is lighter. 🧳",
    "{name} took the elevator down. Pressed every floor on the way out. We don't care. We're free. 🆓",
    "{name} left. Their absence is the upgrade we waited months for. ⭐",
    "{name} is gone. The chat finally smells like clean air and possibility. 🌬️",
    "{name} left. Even autocorrect refused to fix their last message. It knew. ❌",
    "{name} departed. We tried to be sad. We failed. We will not be trying again. 🫡",
    # ---- batch 3: built to hurt ----
    "{name} left. Nobody noticed for the first eleven minutes. Nobody minded for the rest. 🤍",
    "{name} is gone. The group has been quietly thriving in the seconds since. Run the numbers, they're brutal. 📉",
    "{name} left. We checked their chat history for one good moment. We're still checking. We've lost faith. 🕯️",
    "{name} packed up and left. Don't take it personally — the chat felt like this years before they pressed the button. 💔",
    "{name} departed. The hardest part was admitting we all stayed in this group longer than we stayed friends with them. 📜",
    "{name} left. Statistically, this is the version of them this chat will remember best. Hold it close. 🫥",
    "{name} is gone. Their group photo will be replaced with a blank pixel — a 1:1 representation of their impact. ⬛",
    "{name} left. We thought about saying something nice. We sat with the silence. The silence said it better. 🔇",
    "{name} departed. The notification said 'left the group.' It could have said 'finally understood.' 🪞",
    "{name} is gone. Twelve people in this chat noticed before you did. None of them are sad. 😶",
    "{name} left. There is a version of this story where they were missed. We're not in it. We've never been in it. 📖",
    "{name} packed up. They were always packing up. They just finally walked out the door we'd been holding open. 🚪",
    "{name} departed. The kindest thing we can do is not pretend we'll wonder how they're doing. 🪦",
    "{name} left. Their last message will sit unanswered in our backlog forever — same place it was always headed. 📩",
    "{name} is gone. The group photo composition just improved, the air just lightened, and three people just exhaled. 🌬️",
    "{name} left. If you're reading this with the wrong feelings, that's the part to sit with. We've already moved on. 🪷",
    "{name} departed. We checked who'd notice if they left. Nobody put their hand up. The vote was unanimous. ✋",
    "{name} is gone. Their absence is louder than anything they ever said here. Quieter, somehow, too. 🌫️",
    "{name} left. The polite thing would be a tribute. We'd rather be honest. The honest thing is a paragraph break. ❎",
    "{name} packed their things. We helped. Quietly. For months. They never noticed. They were never going to. 🧹",
    "{name} departed. The group chat survives. The friendships survive. The impression they made does not. 🍂",
    "{name} left. We rewrote the group description in their honor. We removed two words. They were their name. ✂️",
    "{name} is gone. They came in with a bang. They leave with a footnote. Most of us couldn't pick the font. 📝",
    "{name} departed. Look around the chat. Nobody is looking back at the door. They never were. 🪟",
    "{name} left. We'll never know which message of ours was the last one they read. We'll never wonder, either. 📬",
    "{name} is gone. The version of them that lived in this chat dies with the notification. We won't be lighting candles. 🕯️",
    "{name} left. We'd say the door is always open. It isn't. It locked itself. The chat picked the locksmith. 🔐",
    "{name} departed. If you're hoping for closure — same. Closure isn't coming. It was never theirs to give. 🛑",
    "{name} is gone. The group will keep going, exactly as it always has, just a little lighter. That's the whole eulogy. 🤍",
    "{name} left. Read this slowly: nobody asked them to stay. Nobody is going to. That's not cruelty. That's just the room. 🪑",
]

_HISTORY_SIZE = 18

# Batch 4: brutal but clean — no slurs, no SA references, no named bystanders.
# Drawn at the rate below instead of from the main pool.
EXTREME_MESSAGES = [
    "{name} left. Ghop ghop ghop. The door doesn't even bother slamming for them. 🚪",
    "{name} is gone. We held a vote on whether to grieve. Zero votes. Motion carried. 📋",
    "{name} departed. They printed their participation trophy. We threw it in the recycling. ♻️",
    "{name} left. The chat held its breath. Then realized it had been holding it the whole time they were here. 🫧",
    "{name} packed up. Their luggage was lighter than the impression they left. ✈️",
    "{name} is gone. We tried to write something kind. The cursor blinked at us in pity. 💻",
    "{name} left. Even the unread counter laughed. 0. 0 unread. 0 missed. 0 wondered. 0️⃣",
    "{name} departed. The group did the math. Their net contribution was a negative number. 🔢",
    "{name} is gone. Their seat in the chat has been declared a haunted spot. We're roping it off. ⚠️",
    "{name} left. The eulogy was one line: 'they were here.' Nobody requested an encore. 📜",
    "{name} packed up. They thought leaving would punish us. We sent flowers. To ourselves. 💐",
    "{name} is gone. The chat ran a diagnostic. Nothing was missing. ✅",
    "{name} departed. We checked their pinned messages. None. Because they had none worth pinning. 📌",
    "{name} left. Ghop ghop ghop. The dust settles. The chat hums. The void inherits them now. 🌑",
    "{name} is gone. We tried to remember the last thing they said. We tried. We are still trying. We give up. ⏳",
    "{name} packed up. They left a forwarding address. We won't be forwarding anything. 📬",
    "{name} departed. The group went around the room sharing favorite memories. The room stayed quiet. 🤐",
    "{name} left. The chat upgraded itself. No installation required. Default option: they aren't here. ✨",
    "{name} is gone. Their digital footprint here was a wet leaf. The wind took it. 🍃",
    "{name} packed up. We sat down to compile a list of reasons they'd be missed. We're recycling the paper. ♻️",
]

# Roughly 1 in 5 leaves pulls from the EXTREME pool.
_EXTREME_RATE = 0.20

_lock = Lock()
_recent: dict[tuple[int, str], deque] = {}


def pick(chat_id: int) -> str:
    """Return a message with `{name}` placeholder, avoiding recent repeats.

    With probability `_EXTREME_RATE` the line comes from the dialed-up
    EXTREME_MESSAGES pool; otherwise the main savage pool.
    """
    with _lock:
        if random.random() < _EXTREME_RATE:
            pool, key = EXTREME_MESSAGES, "extreme"
        else:
            pool, key = MESSAGES, "normal"
        history = _recent.setdefault((chat_id, key), deque(maxlen=_HISTORY_SIZE))
        choices = [i for i in range(len(pool)) if i not in history]
        if not choices:
            choices = list(range(len(pool)))
            history.clear()
        idx = random.choice(choices)
        history.append(idx)
        return pool[idx]
