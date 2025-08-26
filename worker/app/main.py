import os
import json
import time
import threading
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
API_HOST = os.getenv("API_HOST", "127.0.0.1")
r = redis.from_url(REDIS_URL)

def job_key(jid: str) -> str:
    return f"job:{jid}"

def set_status(jid: str, **fields):
    r.hset(job_key(jid), mapping=fields)

def _process_job(payload: dict):
    jid = payload["id"]
    kind = payload.get("kind", "")
    set_status(jid, status="processing", kind=kind, error="")
    print(f"[worker] take job: {jid} kind={kind}")

    try:
        if kind == "render_webp":
            pdf_path = Path(payload["path"])
            watermark_text = payload.get("watermark_text")
            t0 = time.time()
            pages, _ = render_pdf_to_webp(pdf_path, watermark_text, timeout_sec=RENDER_TIMEOUT_SEC)
            h = sha256_file(pdf_path)
            link = materialize_first_page(h)
            url = f"http://{API_HOST}:8000/files/{link.name}" if link else None
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

def _consumer_loop():
    # бесконечный консюмер очереди
    while True:
        try:
            item = r.blpop("jobs", timeout=5)
            if not item:
                continue
            _, payload = item
            job = json.loads(payload.decode())
            _process_job(job)
        except Exception as e:
            print("[worker] consumer error:", e)
            time.sleep(1)

@app.on_event("startup")
async def startup():
    print("[worker] startup ok")
    for d in (DATA_DIR, PDF_DIR, CACHE_DIR, OUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    # запускаем фонового консюмера
    t = threading.Thread(target=_consumer_loop, name="queue-consumer", daemon=True)
    t.start()

@app.get("/healthz")
def healthz():
    return {"status": "ok", "service": "worker"}

# этот ручной триггер можно оставить «на всякий» для отладки
@app.get("/work")
def work():
    item = r.blpop("jobs", timeout=1)
    if not item:
        return {"tick": True}
    _, payload = item
    job = json.loads(payload.decode())
    _process_job(job)
    return {"ok": True}
