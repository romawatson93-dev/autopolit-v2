import os
import asyncio
from fastapi import FastAPI
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from contextlib import suppress

app = FastAPI(title="autopolit-v2 BOT")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
BOT_MODE = os.getenv("BOT_MODE", "polling").strip().lower()

bot: Bot | None = None
dp: Dispatcher | None = None
_polling_task: asyncio.Task | None = None

@app.get("/healthz")
async def healthz():
    status = "ok"
    details = {"service":"bot","mode":BOT_MODE}
    if not TELEGRAM_BOT_TOKEN:
        details["bot"] = "no_token"
    else:
        details["bot"] = "ready"
    return {"status": status, **details}

def _build_bot():
    global bot, dp
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def on_start(message: types.Message):
        await message.answer("Привет! Я бот autopolit-v2. Отправь любое сообщение — я повторю его.")

    @dp.message()
    async def echo(message: types.Message):
        await message.answer(message.text or "👍")

async def _start_polling():
    assert bot and dp
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

@app.on_event("startup")
async def on_startup():
    global _polling_task
    if TELEGRAM_BOT_TOKEN and BOT_MODE == "polling":
        _build_bot()
        loop = asyncio.get_running_loop()
        _polling_task = loop.create_task(_start_polling())

@app.on_event("shutdown")
async def on_shutdown():
    global _polling_task, bot
    with suppress(Exception):
        if _polling_task:
            _polling_task.cancel()
    with suppress(Exception):
        if bot:
            await bot.session.close()
