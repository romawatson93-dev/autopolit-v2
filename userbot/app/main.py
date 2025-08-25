from fastapi import FastAPI

app = FastAPI(title="autopolit-v2 USERBOT")

@app.get("/healthz")
def healthz():
    # сюда придёт логика Telethon/TDLib
    return {"status": "ok", "service": "userbot"}
