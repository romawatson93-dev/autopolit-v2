import os
from fastapi import FastAPI
from telethon import TelegramClient

app = FastAPI(title="autopolit-v2 USERBOT")

API_ID = os.getenv("TELETHON_API_ID", "").strip()
API_HASH = os.getenv("TELETHON_API_HASH", "").strip()
SESSION_NAME = os.getenv("TELETHON_SESSION", "userbot.session").strip()

client: TelegramClient | None = None
connected: bool = False
reason: str = "init"

@app.on_event("startup")
async def on_startup():
    global client, connected, reason
    if not API_ID or not API_HASH:
        reason = "no_creds"
        return
    try:
        # session file хранится внутри контейнера в рабочей директории
        client = TelegramClient(SESSION_NAME, int(API_ID), API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            # сессии нет или не авторизована — позже создадим интерактивно
            connected = False
            reason = "no_session"
            await client.disconnect()
            client = None
            return
        connected = True
        reason = "ok"
    except Exception as e:
        connected = False
        reason = f"error: {e!s}"

@app.on_event("shutdown")
async def on_shutdown():
    global client
    if client and client.is_connected():
        await client.disconnect()

@app.get("/healthz")
def healthz():
    status = "ok" if connected else "fail"
    return {"status": status, "service": "userbot", "detail": reason}
