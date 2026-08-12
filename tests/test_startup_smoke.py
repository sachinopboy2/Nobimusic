"""Startup smoke test — imports every module the bot loads at runtime,
without touching Telegram. Catches import-time crashes (syntax errors,
missing symbols, bad top-level code) before deploy.

Run: .venv/bin/python tests/test_startup_smoke.py
"""
import importlib
import os
import pkgutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

failed = []

# bot.start pulls in client, config, music, playback — the full startup
# import chain short of .start() network calls.
for mod in ["main", "bot.start"]:
    try:
        importlib.import_module(mod)
        print(f"PASS  import {mod}")
    except Exception as exc:
        failed.append((mod, exc))
        print(f"FAIL  import {mod}: {type(exc).__name__}: {exc}")

# Every plugin (pyrofork auto-loads all of bot/plugins/* at app.start(),
# so an import crash in ANY of them kills startup) and every util.
import bot.plugins
import bot.utils

for pkg in (bot.plugins, bot.utils):
    for info in pkgutil.iter_modules(pkg.__path__):
        name = f"{pkg.__name__}.{info.name}"
        try:
            importlib.import_module(name)
            print(f"PASS  import {name}")
        except Exception as exc:
            failed.append((name, exc))
            print(f"FAIL  import {name}: {type(exc).__name__}: {exc}")

print(f"\n{'FAIL' if failed else 'PASS'}: {len(failed)} import failure(s)")
sys.exit(1 if failed else 0)
