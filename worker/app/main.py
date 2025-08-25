import os, json, threading, time
from fastapi import FastAPI
from redis import Redis

app = FastAPI(title="autopolit-v2 WORKER")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
QUEUE_KEY = "jobs"
JOB_PREFIX = "job:"

def r() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)

def process_job(payload: dict) -> dict:
    # имитация работы: преобразуем имя в UPPER и считаем длину
    name = (payload.get("name") or "").strip()
    result = {"upper": name.upper(), "length": len(name)}
    # можно добавить sleep для демонстрации
    time.sleep(0.5)
    return result

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
            payload = data["payload"]
            client.hset(JOB_PREFIX+job_id, mapping={"status":"processing"})
            result = process_job(payload)
            client.hset(JOB_PREFIX+job_id, mapping={
                "status": "done",
                "result": json.dumps(result, ensure_ascii=False)
            })
        except Exception as e:
            # зафиксируем ошибку в job, чтобы видеть причину
            try:
                if "job_id" in locals():
                    client.hset(JOB_PREFIX+job_id, mapping={"status":"error","error":str(e)})
            except Exception:
                pass
            time.sleep(1)

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
