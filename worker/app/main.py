import os, json, threading, time, tempfile, subprocess, shlex, sys
from fastapi import FastAPI
from redis import Redis
import requests

app = FastAPI(title="autopolit-v2 WORKER")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
QUEUE_KEY = "jobs"
JOB_PREFIX = "job:"
DATA_DIR = "/data"

# Настройки (в .env можно менять)
RENDER_DPI = int(os.getenv("RENDER_DPI", "240"))               # высокое, но разумное по скорости
RENDER_TIMEOUT_SEC = int(os.getenv("RENDER_TIMEOUT_SEC", "90"))
RENDER_FALLBACK = os.getenv("RENDER_FALLBACK", "1") == "1"     # включён

def r() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)

def log(*a):
    print("[worker]", *a, file=sys.stderr, flush=True)

def _ensure_output(out_png_path: str, out_prefix: str) -> None:
    if os.path.exists(out_png_path):
        return
    alt = out_prefix + ".png"
    if os.path.exists(alt):
        os.replace(alt, out_png_path)
        return
    raise RuntimeError("renderer did not produce output file")

def _run(cmd: str, timeout_sec: int) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec)

# --- Рендер №1: MuPDF (mutool) — очень быстрый ---
def render_with_mutool(pdf_path: str, out_png_path: str, dpi: int, timeout_sec: int):
    # mutool draw -F png -r <dpi> -o <exact.png> <pdf> 1
    cmd = f"mutool draw -F png -r {dpi} -o {shlex.quote(out_png_path)} {shlex.quote(pdf_path)} 1"
    log("run(mutool):", cmd)
    res = _run(cmd, timeout_sec)
    if res.returncode != 0 and not os.path.exists(out_png_path):
        raise RuntimeError(f"mutool failed ({res.returncode}): {res.stderr.decode('utf-8','ignore')}")

# --- Рендер №2: pdftocairo (fallback) ---
def render_with_pdftocairo(pdf_path: str, out_png_path: str, dpi: int, timeout_sec: int):
    out_prefix = os.path.splitext(out_png_path)[0]
    cmd = f"pdftocairo -png -singlefile -f 1 -l 1 -r {dpi} {shlex.quote(pdf_path)} {shlex.quote(out_prefix)}"
    log("run(pdftocairo):", cmd)
    res = _run(cmd, timeout_sec)
    if res.returncode != 0 and not (os.path.exists(out_png_path) or os.path.exists(out_prefix + '.png')):
        raise RuntimeError(f"pdftocairo failed ({res.returncode}): {res.stderr.decode('utf-8','ignore')}")
    _ensure_output(out_png_path, out_prefix)

# --- Рендер №3: pdftoppm (второй fallback) ---
def render_with_pdftoppm(pdf_path: str, out_png_path: str, dpi: int, timeout_sec: int):
    out_prefix = os.path.splitext(out_png_path)[0]
    cmd = f"pdftoppm -singlefile -png -f 1 -l 1 -r {dpi} {shlex.quote(pdf_path)} {shlex.quote(out_prefix)}"
    log("run(pdftoppm):", cmd)
    res = _run(cmd, timeout_sec)
    if res.returncode != 0 and not (os.path.exists(out_png_path) or os.path.exists(out_prefix + '.png')):
        raise RuntimeError(f"pdftoppm failed ({res.returncode}): {res.stderr.decode('utf-8','ignore')}")
    _ensure_output(out_png_path, out_prefix)

def render_first_page(pdf_path: str, out_png_path: str):
    # 1) Сначала пробуем MuPDF (быстро и качественно)
    try:
        render_with_mutool(pdf_path, out_png_path, dpi=RENDER_DPI, timeout_sec=RENDER_TIMEOUT_SEC)
        return
    except Exception as e:
        log(f"mutool error: {e}")
    # 2) Fallback на pdftocairo
    if RENDER_FALLBACK:
        try:
            render_with_pdftocairo(pdf_path, out_png_path, dpi=RENDER_DPI, timeout_sec=RENDER_TIMEOUT_SEC)
            return
        except Exception as e:
            log(f"pdftocairo error: {e}")
        # 3) Второй fallback на pdftoppm
        try:
            render_with_pdftoppm(pdf_path, out_png_path, dpi=RENDER_DPI, timeout_sec=RENDER_TIMEOUT_SEC)
            return
        except Exception as e:
            log(f"pdftoppm error: {e}")
    raise RuntimeError("all renderers failed or timed out")

# ==== обработчики ====
def handle_echo(payload: dict) -> dict:
    name = (payload.get("name") or "").strip()
    time.sleep(0.2)
    return {"upper": name.upper(), "length": len(name)}

def _render_from_pdf_path(pdf_path: str, job_id: str) -> dict:
    out_path = os.path.join(DATA_DIR, f"{job_id}.png")
    render_first_page(pdf_path, out_path)
    return {"pages": 1, "png": f"{job_id}.png", "url": f"http://127.0.0.1:8000/files/{job_id}.png"}

def handle_render(payload: dict, job_id: str) -> dict:
    local_path = payload.get("local_path")
    doc_url = payload.get("doc_url")

    if local_path:
        if not os.path.exists(local_path):
            return {"error": f"local file not found: {local_path}"}
        log(f"render(local): job={job_id} {local_path}")
        return _render_from_pdf_path(local_path, job_id)

    if not doc_url:
        return {"error": "provide doc_url or local_path"}

    log(f"render(url): job={job_id} {doc_url}")
    with tempfile.TemporaryDirectory() as td:
        pdf_path = os.path.join(td, "doc.pdf")
        with requests.get(doc_url, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            with open(pdf_path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    if chunk:
                        f.write(chunk)
        return _render_from_pdf_path(pdf_path, job_id)

HANDLERS = {
    "echo": lambda payload, job_id=None: handle_echo(payload),
    "render": handle_render,
}

def worker_loop():
    client = r()
    while True:
        try:
            item = client.brpop(QUEUE_KEY, timeout=1)
            if not item:
                continue
            _, raw = item
            data = json.loads(raw)
            job_id = data["id"]
            kind = data.get("kind", "generic")
            payload = data.get("payload", {})

            log(f"take job: {job_id} kind={kind}")
            client.hset(JOB_PREFIX+job_id, mapping={"status":"processing","kind":kind})
            handler = HANDLERS.get(kind)
            if handler is None:
                client.hset(JOB_PREFIX+job_id, mapping={"status":"error","error":f"unknown kind: {kind}"})
                log(f"unknown kind: {kind}")
                continue

            try:
                if kind == "render":
                    res = handler(payload, job_id=job_id)
                else:
                    res = handler(payload)
                client.hset(JOB_PREFIX+job_id, mapping={
                    "status": "done",
                    "result": json.dumps(res, ensure_ascii=False),
                    "kind": kind,
                })
                log(f"done job: {job_id}")
            except subprocess.TimeoutExpired:
                client.hset(JOB_PREFIX+job_id, mapping={"status":"error","error":"render timeout"})
                log(f"timeout job: {job_id}")
            except Exception as e:
                client.hset(JOB_PREFIX+job_id, mapping={"status":"error","error":str(e)})
                log(f"error job: {job_id} -> {e}")

        except Exception as e:
            log(f"loop error: {e}")
            time.sleep(0.5)

@app.on_event("startup")
def startup():
    t = threading.Thread(target=worker_loop, daemon=True)
    t.start()
    log("startup ok")

@app.get("/healthz")
def healthz():
    try:
        r().ping()
        return {"status": "ok", "service": "worker", "redis": "ok"}
    except Exception:
        return {"status": "fail", "service": "worker", "redis": "fail"}
