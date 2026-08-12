"""Lazy holder for the PyTgCalls instance.

`PyTgCalls(userbot)` captures asyncio state (self.loop, internal locks,
ChatLock, Cache, NTgCalls bindings) at __init__ time. On Python 3.10+
that's the import-time loop, distinct from the one asyncio.run() creates.
Constructing inside the running loop avoids every cross-loop Future error
that surfaces as "Task got Future attached to a different loop" during
`music.play()`.

Usage:
- `init(userbot_client)` from inside the running loop (bot.start._run).
- Other modules access `music` via the module attribute
  (`from bot.utils import music as music_mod; music_mod.music.play(...)`)
  rather than a name-bound `from bot.utils.music import music`. Plugin
  files imported by pyrofork's load_plugins() happen AFTER init() so a
  symbol-import there is safe.
"""

music = None  # populated by init()


def init(client) -> None:
    """Construct PyTgCalls. Must be called inside the running loop."""
    global music
    if music is not None:
        return
    from pytgcalls import PyTgCalls
    music = PyTgCalls(client)
