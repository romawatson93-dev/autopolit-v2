import os
from fastapi import FastAPI, Query
from sqlalchemy import text
from .db import engine
from .queue import enqueue_task, get_job

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

@app.post("/enqueue")
def enqueue(name: str = Query(..., description="имя для обработки")):
    job_id = enqueue_task({"name": name}, kind="echo")
    return {"job_id": job_id, "queued": True}

@app.post("/render")
def render(doc_url: str = Query(..., description="URL документа для рендера")):
    # пока заглушка: просто кладём задание с kind=render
    job_id = enqueue_task({"doc_url": doc_url}, kind="render")
    return {"job_id": job_id, "queued": True}

@app.get("/job/{job_id}")
def job_status(job_id: str):
    data = get_job(job_id)
    if not data:
        return {"exists": False}
    return {"exists": True, **data}
