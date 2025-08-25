from fastapi import FastAPI

app = FastAPI(title="autopolit-v2 API")

@app.get("/healthz")
def healthz():
    return {"status": "ok"}
