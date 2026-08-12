"""Centralized premium custom-emoji IDs/snippets for Warborn Music."""
import html as _html

def _e(eid: str, glyph: str) -> str:
    return f'<emoji id="{eid}">{glyph}</emoji>'

def mention(user) -> str:
    if user is None:
        return "someone"
    name = _html.escape(getattr(user, "first_name", None) or "user")
    return f'<a href="tg://user?id={user.id}">{name}</a>'

# ── Existing IDs (untouched) ──────────────────────
NOTE_ID="5994721794760642534"; MUSIC_ID="5334653529741076580"
HEAD_ID="5886268068035827289"; BOLT_ID="6170427231802757303"
FIRE_ID="5346334981792734939"; BRAIN_ID="5278628322769654561"
PEOPLE_ID="5861955787181525936"; USER_ID="5226810560250676186"
SHIELD_ID="4958900559139570572"; CROWN_ID="6231116549919349944"
WAVE_ID="5816875690183631180"; GEAR_ID="5341715473882955310"
IDCARD_ID="5350427505805238170"; DICE_ID="5972061723400605896"
SPARKLE_ID="5271810272640643747"; WAND_ID="5269617691836058799"
CHAT_ID="5443038326535759644"; PLUS_ID="5030749344752468962"
MEGA_ID="4967957395331351254"; BOOK_ID="5033104253846029290"

# ── New premium IDs (guide emojis) ────────────────
NEW_NOTE_ID     = "6086714986309097798"  # 💜
NEW_MUSIC_ID    = "5409025823388741707"  # 🎵
CLOCK_ID        = "5408910404732595664"  # 🕐
COMET_ID        = "5041992177563993101"  # ☄️
WARNING_ID      = "5039665997506675838"  # ⚠️
LIPS_ID         = "5039661745489052379"  # 🫦
ROSE1_ID        = "5039850573726221609"  # 🌹
COOL_ID         = "5424663180838182778"  # 😎
BOUQUET_ID      = "6089064797276477848"  # 💐
CHEERS_ID       = "6088902851239613437"  # 🥂
DIAMOND_ID      = "5039816072253932764"  # 💎
NEW_CROWN_ID    = "5041792560368977040"  # 👑
TEDDY_ID        = "5042192219960771668"  # 🧸
HEART_EYES_ID   = "6219504684927816093"  # 😻
HEART_ID        = "6217365353127744430"  # ❤️
SUN_ID          = "5436356474114685168"  # ☀️
RED_SQ1_ID      = "5438522812669111826"  # 🟥
STAR_EYES_ID    = "5226841501195065587"  # 🤩
ROSE2_ID        = "5226806553046178400"  # 🌹
BOW_ID          = "5226654678707622609"  # 🎀
CHECK_ID        = "5469715729915859659"  # ✔️
CRESCENT_ID     = "5283223151797364771"  # ☪
INFINITY_ID     = "5469931384518755322"  # ♾
BOLT2_ID        = "5343819952023428595"  # ⚡️
BOLT3_ID        = "5341463333532882949"  # ⚡️
EYES_ID         = "5408972372520743709"  # 👀
SLIDER_ID       = "5210688971008391086"  # 🎚
INBOX_ID        = "5443127283898405358"  # 📥
PIN_ID          = "5039600026809009149"  # 📌
PROFILE_ID      = "5408846628763217930"  # 👤
RED_SQ2_ID      = "5436345165465794033"  # 🟥
BUTTERFLY_ID    = "5084613633418199991"  # 🦋
HEART_ORGAN_ID  = "5116296632203216188"  # 🫀
KNOB_ID         = "5116444615301399317"  # 🔘
SPARKLE2_ID     = "5134202243486057363"  # 💫
RAINBOW_ID      = "4904819211416633963"  # 🌈
BOMB1_ID        = "5134377151734219769"  # 💣
BOMB2_ID        = "6138798143447244059"  # 💣
SEARCH_ID       = "5258274739041883702"  # 🔍
NEW_FIRE_ID     = "5222148368955877900"  # 🔥
SMILE_ID        = "6219579614927261727"  # ☺️
DART_ID         = "6219579614927261727"  # 🎯
GHOST_ID        = "5082478549340783285"  # 👻
BLOCK_ID        = "5116151848855667552"  # 🚫
THUMBS_DOWN_ID  = "5121063440311386962"  # 👎
NO_ENTRY_ID     = "4918014360267260850"  # ⛔️

# ── Snippets (existing) ───────────────────────────
NOTE=_e(NOTE_ID,"🎵"); MUSIC=_e(MUSIC_ID,"🎶"); HEAD=_e(HEAD_ID,"🎧")
BOLT=_e(BOLT_ID,"⚡"); FIRE=_e(FIRE_ID,"🔥"); BRAIN=_e(BRAIN_ID,"🧠")
PEOPLE=_e(PEOPLE_ID,"👥"); USER=_e(USER_ID,"👤"); SHIELD=_e(SHIELD_ID,"🛡")
CROWN=_e(CROWN_ID,"👑"); WAVE=_e(WAVE_ID,"👋"); GEAR=_e(GEAR_ID,"⚙️")
IDCARD=_e(IDCARD_ID,"🆔"); DICE=_e(DICE_ID,"🎲"); SPARKLE=_e(SPARKLE_ID,"🔮")
WAND=_e(WAND_ID,"🪄"); CHAT=_e(CHAT_ID,"💬"); PLUS=_e(PLUS_ID,"➕")
MEGA=_e(MEGA_ID,"📢"); BOOK=_e(BOOK_ID,"📚")

# ── New snippets (premium animated) ───────────────
NOTE_NEW    = _e(NEW_NOTE_ID, "💜")
MUSIC_NEW   = _e(NEW_MUSIC_ID, "🎵")
CLOCK       = _e(CLOCK_ID, "🕐")
COMET       = _e(COMET_ID, "☄️")
WARNING     = _e(WARNING_ID, "⚠️")
LIPS        = _e(LIPS_ID, "🫦")
ROSE1       = _e(ROSE1_ID, "🌹")
COOL        = _e(COOL_ID, "😎")
BOUQUET     = _e(BOUQUET_ID, "💐")
CHEERS      = _e(CHEERS_ID, "🥂")
DIAMOND     = _e(DIAMOND_ID, "💎")
CROWN_NEW   = _e(NEW_CROWN_ID, "👑")
TEDDY       = _e(TEDDY_ID, "🧸")
HEART_EYES  = _e(HEART_EYES_ID, "😻")
HEART       = _e(HEART_ID, "❤️")
SUN         = _e(SUN_ID, "☀️")
RED_SQ1     = _e(RED_SQ1_ID, "🟥")
STAR_EYES   = _e(STAR_EYES_ID, "🤩")
ROSE2       = _e(ROSE2_ID, "🌹")
BOW         = _e(BOW_ID, "🎀")
CHECK       = _e(CHECK_ID, "✔️")
CRESCENT    = _e(CRESCENT_ID, "☪")
INFINITY    = _e(INFINITY_ID, "♾")
BOLT2       = _e(BOLT2_ID, "⚡️")
BOLT3       = _e(BOLT3_ID, "⚡️")
EYES        = _e(EYES_ID, "👀")
SLIDER      = _e(SLIDER_ID, "🎚")
INBOX       = _e(INBOX_ID, "📥")
PIN         = _e(PIN_ID, "📌")
PROFILE     = _e(PROFILE_ID, "👤")
RED_SQ2     = _e(RED_SQ2_ID, "🟥")
BUTTERFLY   = _e(BUTTERFLY_ID, "🦋")
HEART_ORGAN = _e(HEART_ORGAN_ID, "🫀")
KNOB        = _e(KNOB_ID, "🔘")
SPARKLE2    = _e(SPARKLE2_ID, "💫")
RAINBOW     = _e(RAINBOW_ID, "🌈")
BOMB1       = _e(BOMB1_ID, "💣")
BOMB2       = _e(BOMB2_ID, "💣")
SEARCH      = _e(SEARCH_ID, "🔍")
FIRE_NEW    = _e(NEW_FIRE_ID, "🔥")
SMILE       = _e(SMILE_ID, "☺️")
DART        = _e(DART_ID, "🎯")
GHOST       = _e(GHOST_ID, "👻")
BLOCK       = _e(BLOCK_ID, "🚫")
THUMBS_DOWN = _e(THUMBS_DOWN_ID, "👎")
NO_ENTRY    = _e(NO_ENTRY_ID, "⛔️")

# ── Symbols (for fancy UI) ────────────────────────
STAR        = "✦"
SEPARATOR   = "━━━━━━━━━━━━━━"
DOT         = "•"
ARROW       = "➤"
HEART_ICON  = "❤️‍🔥"
BOT_TAG     = "🩵"
