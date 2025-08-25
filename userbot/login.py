from telethon.sync import TelegramClient
import os

api_id = int(os.getenv("TELETHON_API_ID"))
api_hash = os.getenv("TELETHON_API_HASH")
session_name = os.getenv("TELETHON_SESSION", "userbot.session")

# Это интерактивно спросит номер телефона, код из Telegram и (если включено) пароль 2FA
client = TelegramClient(session_name, api_id, api_hash)
client.start()

me = client.get_me()
print("Logged in as:", getattr(me, "username", None) or getattr(me, "first_name", "user"))
client.disconnect()
