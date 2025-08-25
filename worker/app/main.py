from fastapi import FastAPI

app = FastAPI(title="autopolit-v2 WORKER")

@app.get("/healthz")
def healthz():
    # здесь позже появятся фоновые задачи/очереди
    return {"status": "ok", "service": "worker"}
