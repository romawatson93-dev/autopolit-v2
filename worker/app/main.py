import os
import json
import time
from fastapi import FastAPI
from pathlib import Path
import redis
from .fast_renderer import (
    DATA_DIR, PDF_DIR, CACHE_DIR, OUT_DIR,
    render_pdf_to_webp, sha256_file, materialize_first_page
)

app = FastAPI()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
RENDER_TIMEOUT_SEC = int(os.getenv("RENDER_TIMEOUT_SEC", "120"))
r = redis.from_url(REDIS_URL)

def job_key(jid: str) -> str:
    return f"job:{jid}"

def set_status(jid: str, **fields):
    r.hset(job_key(jid), mapping=fields)

def get_job(jid: str) -> dict:
    d = r.hgetall(job_key(jid))
    return {k.decode(): v.decode() for k, v in d.items()}

@app.on_event("startup")
async def startup():
    print("[worker] startup ok")
    for d in (DATA_DIR, PDF_DIR, CACHE_DIR, OUT_DIR):
        d.mkdir(parents=True, exist_ok=True)

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "worker"}

@app.get("/work")
def work():
    item = r.blpop("jobs", timeout=1)
    if not item:
        return {"tick": True}
    _, payload = item
    job = json.loads(payload.decode())
    jid = job["id"]
    kind = job.get("kind", "")
    set_status(jid, status="processing", kind=kind, error="")
    print(f"[worker] take job: {jid} kind={kind}")

    try:
        if kind == "render_webp":
            pdf_path = Path(job["path"])
            watermark_text = job.get("watermark_text")
            t0 = time.time()
            pages, _ = render_pdf_to_webp(pdf_path, watermark_text, timeout_sec=RENDER_TIMEOUT_SEC)
            h = sha256_file(pdf_path)
            link = materialize_first_page(h)
            url = None
            if link:
                url = f"http://{os.getenv('API_HOST','127.0.0.1')}:8000/files/{link.name}"
            took = round(time.time() - t0, 3)
            set_status(jid, status="done", result=json.dumps({
                "pages": pages,
                "first_page": link.name if link else None,
                "url": url,
                "hash": h,
                "took_sec": took
            }))
            print(f"[worker] done job: {jid}")
        else:
            set_status(jid, status="error", error=f"unknown kind {kind}")
    except Exception as e:
        set_status(jid, status="error", error=str(e))
    return {"ok": True}