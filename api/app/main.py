import os
import uuid
from fastapi import FastAPI, Query, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy import text
from .db import engine
from .queue import enqueue_task, get_job

app = FastAPI(title="autopolit-v2 API")

DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)

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
    job_id = enqueue_task({"doc_url": doc_url}, kind="render")
    return {"job_id": job_id, "queued": True}

@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    # простая валидация расширения
    fname = file.filename or "upload.pdf"
    ext = os.path.splitext(fname)[1].lower()
    if ext not in {".pdf"}:
        raise HTTPException(status_code=400, detail="only .pdf allowed")

    # сохраняем в общий том /data с уникальным именем
    uid = str(uuid.uuid4())
    saved_name = f"{uid}.pdf"
    dest_path = os.path.join(DATA_DIR, saved_name)
    with open(dest_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            f.write(chunk)

    # кладём задачу на рендер локального файла
    job_id = enqueue_task({"local_path": dest_path}, kind="render")
    return {"job_id": job_id, "queued": True, "source": "upload", "file": saved_name}

@app.get("/job/{job_id}")
def job_status(job_id: str):
    data = get_job(job_id)
    if not data:
        return {"exists": False}
    return {"exists": True, **data}

@app.get("/files/{name}")
def get_file(name: str):
    # защита от path traversal
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="invalid name")
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path)
