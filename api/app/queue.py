import os, json, uuid
from redis import Redis

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

def _r() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)

QUEUE_KEY = "jobs"
JOB_PREFIX = "job:"

def enqueue_task(payload: dict, kind: str = "generic") -> str:
    job_id = str(uuid.uuid4())
    r = _r()
    r.hset(JOB_PREFIX+job_id, mapping={"status":"queued","kind":kind})
    r.lpush(QUEUE_KEY, json.dumps({"id": job_id, "kind": kind, "payload": payload}))
    return job_id

def get_job(job_id: str) -> dict | None:
    r = _r()
    data = r.hgetall(JOB_PREFIX+job_id)
    return data or None
