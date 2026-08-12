"""Two-phase pyrofork string-session generator.

Usage:
  python scripts/session_gen.py send <phone_in_e164>
    → asks Telegram to send a login code to that phone
    → persists dc_id + auth_key (base64) + phone_code_hash to /tmp/sessgen.json

  python scripts/session_gen.py verify <code> [<2fa_password>]
    → completes sign-in and prints "STRING_SESSION=<value>" to stdout

API_ID / API_HASH are read from the project .env via python-dotenv.

We don't use Client.export_session_string between phases because that
helper packs `user_id` into the string and `user_id` is unset until
sign-in. Instead we serialise the raw storage primitives we need
(dc_id + auth_key) and rehydrate them on the verify side.
"""

import asyncio
import base64
import json
import os
import sys

from dotenv import load_dotenv
from pyrogram import Client
from pyrogram.errors import SessionPasswordNeeded

load_dotenv()
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
STATE = "/tmp/sessgen.json"


async def _read_storage(c):
    """Pyrofork's storage exposes async getters in 2.x. Return
    (dc_id, auth_key_bytes, test_mode).
    """
    dc_id = await c.storage.dc_id()
    auth_key = await c.storage.auth_key()
    test_mode = await c.storage.test_mode()
    return dc_id, auth_key, test_mode


async def _write_storage(c, dc_id, auth_key, test_mode):
    await c.storage.dc_id(dc_id)
    await c.storage.auth_key(auth_key)
    await c.storage.test_mode(test_mode)
    await c.storage.api_id(API_ID)
    await c.storage.is_bot(False)
    await c.storage.user_id(0)


async def send(phone: str) -> None:
    c = Client("sessgen", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    await c.connect()
    sent = await c.send_code(phone)
    dc_id, auth_key, test_mode = await _read_storage(c)
    await c.disconnect()
    with open(STATE, "w") as f:
        json.dump(
            {
                "phone": phone,
                "phone_code_hash": sent.phone_code_hash,
                "dc_id": dc_id,
                "auth_key_b64": base64.b64encode(auth_key).decode(),
                "test_mode": test_mode,
            },
            f,
        )
    os.chmod(STATE, 0o600)
    print(f"OK send: code-type={sent.type} timeout={sent.timeout}")


async def verify(code: str, password: str | None) -> None:
    with open(STATE) as f:
        state = json.load(f)
    c = Client("sessgen", api_id=API_ID, api_hash=API_HASH, in_memory=True)
    # Hydrate storage BEFORE connect so it doesn't initiate a fresh auth.
    await c.storage.open()
    await _write_storage(
        c,
        state["dc_id"],
        base64.b64decode(state["auth_key_b64"]),
        state["test_mode"],
    )
    await c.connect()
    try:
        await c.sign_in(state["phone"], state["phone_code_hash"], code)
    except SessionPasswordNeeded:
        if not password:
            await c.disconnect()
            print("ERR: 2FA password required. Re-run: verify <code> <password>")
            sys.exit(2)
        await c.check_password(password)
    final = await c.export_session_string()
    await c.disconnect()
    print("STRING_SESSION=" + final)


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: session_gen.py {send <phone> | verify <code> [<password>]}")
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "send":
        asyncio.run(send(sys.argv[2]))
    elif cmd == "verify":
        pwd = sys.argv[3] if len(sys.argv) >= 4 else None
        asyncio.run(verify(sys.argv[2], pwd))
    else:
        print(f"unknown command: {cmd}")
        sys.exit(2)


if __name__ == "__main__":
    main()
