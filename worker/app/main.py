import os, json, threading, time
from fastapi import FastAPI
from redis import Redis

app = FastAPI(title="autopolit-v2 WORKER")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
QUEUE_KEY = "jobs"
JOB_PREFIX = "job:"

def r() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)

# ==== обработчики задач ====
def handle_echo(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    time.sleep(0.2)
    return {"upper": name.upper(), "length": len(name)}

def handle_render(payload: dict) -> dict:
    doc_url = payload.get("doc_url", "")
    # заглушка: «рендерим» во что-то вроде PNG-ресурса
    time.sleep(0.5)
    return {
        "pages": 1,
        "preview_png": f"render://preview?src={doc_url}",
        "note": "stub-render-ok"
    }

HANDLERS = {
    "echo": handle_echo,
    "render": handle_render,
}

def worker_loop():
    client = r()
    while True:
        try:
            item = client.brpop(QUEUE_KEY, timeout=1)  # (key, value) или None
            if not item:
                continue
            _, raw = item
            data = json.loads(raw)
            job_id = data["id"]
            kind = data.get("kind", "generic")
            payload = data.get("payload", {})

            client.hset(JOB_PREFIX+job_id, mapping={"status":"processing","kind":kind})
            handler = HANDLERS.get(kind)
            if handler is None:
                client.hset(JOB_PREFIX+job_id, mapping={"status":"error","error":f"unknown kind: {kind}"})
                continue

            result = handler(payload)
            client.hset(JOB_PREFIX+job_id, mapping={
                "status": "done",
                "result": json.dumps(result, ensure_ascii=False),
                "kind": kind,
            })
        except Exception as e:
            try:
                if "job_id" in locals():
                    client.hset(JOB_PREFIX+job_id, mapping={"status":"error","error":str(e)})
            except Exception:
                pass
            time.sleep(0.5)

@app.on_event("startup")
def startup():
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()

@app.get("/healthz")
def healthz():
    try:
        r().ping()
        return {"status": "ok", "service": "worker", "redis": "ok"}
    except Exception:
        return {"status": "fail", "service": "worker", "redis": "fail"}
