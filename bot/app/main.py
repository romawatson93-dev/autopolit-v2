from fastapi import FastAPI

app = FastAPI(title="autopolit-v2 BOT")

@app.get("/healthz")
def healthz():
    # потом добавим webhook и обработчики
    return {"status": "ok", "service": "bot"}
