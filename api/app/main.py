import os
import json
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from typing import Optional
from pathlib import Path
import redis
from sqlalchemy import select
from .db import get_session
from .models import Client

app = FastAPI()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
r = redis.from_url(REDIS_URL)

DATA_DIR = Path("/data")
OUT_DIR = DATA_DIR / "out"
PDF_DIR = DATA_DIR / "pdf"
for d in (DATA_DIR, OUT_DIR, PDF_DIR):
    d.mkdir(parents=True, exist_ok=True)

def job_key(jid: str) -> str:
    return f"job:{jid}"

def get_job(jid: str) -> dict:
    d = r.hgetall(job_key(jid))
    return {k.decode(): v.decode() for k, v in d.items()}

@app.get("/healthz")
def healthz():
    try:
        with get_session() as s:
            s.execute(select(Client.id)).first()
        db_status = "ok"
    except Exception:
        db_status = "fail"
    return {"status": "ok", "db": db_status}

@app.post("/clients")
def create_client(name: str = Form(...), watermark_text: Optional[str] = Form(None)):
    with get_session() as s:
        exists = s.execute(select(Client).where(Client.name == name)).scalar_one_or_none()
        if exists:
            return {"id": exists.id, "name": exists.name, "watermark_text": exists.watermark_text}
        c = Client(name=name, watermark_text=watermark_text)
        s.add(c)
        s.commit()
        s.refresh(c)
        return {"id": c.id, "name": c.name, "watermark_text": c.watermark_text}

@app.post("/upload")
async def upload(file: UploadFile = File(...), client_id: Optional[int] = Form(None)):
    data = await file.read()
    if not data or len(data) < 10:
        raise HTTPException(status_code=400, detail="empty file")
    pdf_path = PDF_DIR / f"{os.urandom(16).hex()}.pdf"
    pdf_path.write_bytes(data)

    watermark_text = None
    if client_id:
        with get_session() as s:
            c = s.get(Client, client_id)
            if not c:
                raise HTTPException(status_code=404, detail="client not found")
            watermark_text = c.watermark_text

    import uuid
    jid = str(uuid.uuid4())
    payload = {
        "id": jid,
        "kind": "render_webp",
        "path": str(pdf_path),
        "watermark_text": watermark_text
    }
    r.hset(job_key(jid), mapping={"status": "queued", "kind": "render_webp"})
    r.rpush("jobs", json.dumps(payload))
    return {"job_id": jid}

@app.get("/job/{jid}")
def get_status(jid: str):
    d = get_job(jid)
    if not d:
        return {"exists": False}
    return {"exists": True, **d}

@app.get("/files/{name}")
def files(name: str):
    path = OUT_DIR / name
    if not path.exists():
        raise HTTPException(404, "Not Found")
    return FileResponse(str(path), filename=name)