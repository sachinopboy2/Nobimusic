"""Single-process pyrofork string-session generator.

Phases happen inside ONE running event loop, so the phone_code_hash
from send_code is held in memory until sign_in. No file persistence
between phases, no risk of an in-between send_code call expiring the
code.

Usage:
  python scripts/session_gen_unified.py <phone_e164>

Lifecycle:
  1. Connect to Telegram, call send_code(phone).
     Writes /tmp/sess_sent.txt = "SENT" so caller knows the code is out.
  2. Poll /tmp/sess_code.txt every 1s, up to 5 minutes.
     Caller writes "<code>" or "<code> <2fa_password>" to that path.
  3. Read it, sign_in (and check_password if needed), export the
     session string, and write it to /tmp/sess_out.txt.

Output file format:
  /tmp/sess_out.txt — single line, either:
     STRING_SESSION=<value>
  or:
     ERROR: <message>

The caller is responsible for scrubbing /tmp/sess_code.txt and
/tmp/sess_out.txt after consuming them.
"""

import asyncio
import os
import sys
import time

from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.errors import (
    PhoneCodeExpired,
    PhoneCodeInvalid,
    SessionPasswordNeeded,
)

load_dotenv()
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]

CODE_FILE = "/tmp/sess_code.txt"
SENT_FILE = "/tmp/sess_sent.txt"
OUT_FILE = "/tmp/sess_out.txt"
POLL_INTERVAL = 1.0
POLL_TIMEOUT = 300  # seconds


def _write(path: str, body: str) -> None:
    with open(path, "w") as f:
        f.write(body)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


async def run(phone: str) -> None:
    # Clean any leftover artefacts from prior failed runs.
    for p in (SENT_FILE, CODE_FILE, OUT_FILE):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass

    c = Client("sessgen", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    try:
        await c.connect()
        sent = await c.send_code(phone)
        _write(
            SENT_FILE,
            f"SENT type={sent.type} timeout={sent.timeout} t={time.time():.0f}\n",
        )

        # Poll for the operator-supplied code.
        deadline = time.time() + POLL_TIMEOUT
        while time.time() < deadline:
            if os.path.exists(CODE_FILE):
                break
            await asyncio.sleep(POLL_INTERVAL)
        else:
            _write(OUT_FILE, "ERROR: timed out waiting for /tmp/sess_code.txt\n")
            return

        with open(CODE_FILE) as f:
            tokens = f.read().split()
        if not tokens:
            _write(OUT_FILE, "ERROR: /tmp/sess_code.txt was empty\n")
            return
        code = tokens[0]
        password = tokens[1] if len(tokens) > 1 else None

        try:
            await c.sign_in(phone, sent.phone_code_hash, code)
        except SessionPasswordNeeded:
            if not password:
                _write(
                    OUT_FILE,
                    "ERROR: SessionPasswordNeeded (2FA on this account) — "
                    "rerun and include the 2FA password as a second token in "
                    "/tmp/sess_code.txt\n",
                )
                return
            try:
                await c.check_password(password)
            except Exception as exc:
                _write(OUT_FILE, f"ERROR: 2FA check_password failed: {type(exc).__name__}: {exc}\n")
                return
        except (PhoneCodeExpired, PhoneCodeInvalid) as exc:
            _write(OUT_FILE, f"ERROR: {type(exc).__name__}: {exc}\n")
            return
        except Exception as exc:
            _write(OUT_FILE, f"ERROR: sign_in failed: {type(exc).__name__}: {exc}\n")
            return

        final = await c.export_session_string()
        _write(OUT_FILE, "STRING_SESSION=" + final + "\n")
    finally:
        try:
            await c.disconnect()
        except Exception:
            pass


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: session_gen_unified.py <phone_e164>", file=sys.stderr)
        sys.exit(2)
    asyncio.run(run(sys.argv[1]))


if __name__ == "__main__":
    main()
