import os, io, hashlib, json, uuid
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from redis import Redis
from .db import get_session
from .models import Client
from sqlalchemy import select

APP_NAME = os.getenv("APP_NAME", "autopolit-v2")
DATA_DIR = "/data"
PDF_DIR = os.path.join(DATA_DIR, "pdf")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
QUEUE_KEY = "jobs"
JOB_KEY = "job:"

def r() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)

app = FastAPI(title=f"{APP_NAME} API")

@app.get("/healthz")
def healthz():
    try:
        r().ping()
        return {"status":"ok","db":"ok"}
    except Exception:
        return {"status":"fail","db":"fail"}

# ---- Clients ----
@app.post("/clients")
def create_client(name: str = Form(...), watermark_text: str | None = Form(None)):
    with get_session() as s:
        if s.execute(select(Client).where(Client.name==name)).scalar_one_or_none():
            raise HTTPException(status_code=400, detail="client exists")
        c = Client(name=name.strip(), watermark_text=(watermark_text or "").strip() or None)
        s.add(c)
        s.commit()
        s.refresh(c)
        return {"id": c.id, "name": c.name, "watermark_text": c.watermark_text}

@app.get("/clients/{client_id}")
def get_client(client_id: int):
    with get_session() as s:
        c = s.get(Client, client_id)
        if not c:
            raise HTTPException(status_code=404, detail="not found")
        return {"id": c.id, "name": c.name, "watermark_text": c.watermark_text}

# ---- Job status ----
@app.get("/job/{job_id}")
def job_status(job_id: str):
    data = r().hgetall(JOB_KEY + job_id)
    if not data:
        return JSONResponse({"exists": False}, status_code=404)
    return {
        "exists": True,
        "status": data.get("status"),
        "kind": data.get("kind"),
        "result": data.get("result"),
        "error": data.get("error"),
    }

# ---- Serve files (webp) ----
@app.get("/files/{name}")
def get_file(name: str):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="not found")
    # webp отдаём как image/webp
    media_type = "image/webp" if name.lower().endswith(".webp") else "application/octet-stream"
    return FileResponse(path, media_type=media_type)

def _sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256(); h.update(b); return h.hexdigest()

def _cache_key(pdf_sha: str, dpi: int, wm_text: str | None) -> str:
    wm_part = ""
    if wm_text:
        wm_sha = _sha256_bytes(wm_text.encode("utf-8"))[:8]
        wm_part = f"_wm_{wm_sha}"
    return f"{pdf_sha}_d{dpi}{wm_part}"

# ---- Upload PDF -> enqueue render to WEBP (lossless) with optional watermark
@app.post("/upload")
async def upload_pdf(
    file: UploadFile = File(...),
    client_id: int | None = Form(None),
    wm: str | None = Form(None)  # явный текст ватермарки (если не через client_id)
):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="only .pdf allowed")

    # читаем весь PDF в память чтобы посчитать sha
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    pdf_sha = _sha256_bytes(data)

    # определим watermark_text: либо по client_id, либо из wm
    watermark_text = None
    if client_id:
        with get_session() as s:
            c = s.get(Client, client_id)
            if not c:
                raise HTTPException(status_code=404, detail="client not found")
            watermark_text = c.watermark_text
    if wm:
        wm = wm.strip()
        if len(wm) > 200:
            raise HTTPException(status_code=400, detail="watermark too long (<=200 chars)")
        watermark_text = wm

    # базовые пути
    pdf_path = os.path.join(PDF_DIR, f"{pdf_sha}.pdf")
    # DPI считывает воркер, но ключ кэша должен совпасть; пробрасывать не будем: пусть воркер добавит DPI внутрь результата
    # Для кэша берём DPI из .env воркера? — не знаем здесь. Поэтому пусть воркер сам использует тот же ключ.
    # Мы лишь положим PDF на диск.
    if not os.path.exists(pdf_path):
        with open(pdf_path, "wb") as f:
            f.write(data)

    # формируем job
    job_id = str(uuid.uuid4())
    payload = {
        "pdf_sha": pdf_sha,
        "local_pdf": pdf_path,
        "watermark_text": watermark_text or "",
    }
    r().hset(JOB_KEY+job_id, mapping={"status":"queued","kind":"render_webp"})
    r().lpush(QUEUE_KEY, json.dumps({"id": job_id, "kind": "render_webp", "payload": payload}))
    return {"job_id": job_id, "queued": True}
