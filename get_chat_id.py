#!/usr/bin/env python3
"""
Find your Telegram chat ID.

    1. Open Telegram, find your bot, press START and send it any message
       (literally "hi" is fine).
    2. Run:   TELEGRAM_BOT_TOKEN=123456:AA... python3 get_chat_id.py

It prints every chat that has messaged the bot, and sends a confirmation
message back to the first one so you know it works end to end.
"""

import json
import os
import sys
import urllib.parse
import urllib.request

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not TOKEN:
    sys.exit("Set TELEGRAM_BOT_TOKEN first, e.g.\n"
             "  TELEGRAM_BOT_TOKEN=123456:AA... python3 get_chat_id.py")

API = f"https://api.telegram.org/bot{TOKEN}"


def call(method: str, **params):
    url = f"{API}/{method}"
    data = urllib.parse.urlencode(params).encode() if params else None
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=20) as r:
        return json.loads(r.read().decode())


me = call("getMe")
if not me.get("ok"):
    sys.exit(f"Token rejected: {me}")
print(f"Bot: @{me['result']['username']}  ({me['result']['first_name']})\n")

updates = call("getUpdates", timeout=0)
chats = {}
for upd in updates.get("result", []):
    msg = upd.get("message") or upd.get("channel_post") or upd.get("my_chat_member")
    chat = (msg or {}).get("chat")
    if chat:
        chats[chat["id"]] = chat

if not chats:
    sys.exit(
        "No messages found.\n"
        "Open Telegram, press START on your bot, send it any message, then run this again.\n"
        "(If the bot is in a group, send a message in that group instead.)"
    )

print("Chats that have talked to this bot:")
for cid, chat in chats.items():
    label = chat.get("title") or " ".join(
        filter(None, [chat.get("first_name"), chat.get("last_name")])
    ) or chat.get("username", "")
    print(f"  chat_id = {cid}    {chat.get('type'):<10} {label}")

first = next(iter(chats))
print(f"\nSending a test message to {first} ...")
res = call("sendMessage", chat_id=first,
           text="✅ Price alerts connected. This chat ID works.")
print("sent" if res.get("ok") else f"failed: {res}")
print(f"\n→ Use  TELEGRAM_CHAT_ID = {first}")
