import os
from fastapi import FastAPI
from sqlalchemy import text
from .db import engine

app = FastAPI(title="autopolit-v2 API")

@app.get("/healthz")
def healthz():
    db_ok = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok", "db": "ok" if db_ok else "fail"}
