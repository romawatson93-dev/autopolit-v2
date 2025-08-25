import os, sys, json, threading, time, tempfile, subprocess, shlex, hashlib
from fastapi import FastAPI
from redis import Redis
from PIL import Image, ImageDraw, ImageFont
import requests

app = FastAPI(title="autopolit-v2 WORKER")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
QUEUE_KEY = "jobs"
JOB_PREFIX = "job:"
DATA_DIR = "/data"
PDF_DIR = os.path.join(DATA_DIR, "pdf")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
os.makedirs(PDF_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)

RENDER_DPI = int(os.getenv("RENDER_DPI", "300"))
RENDER_TIMEOUT_SEC = int(os.getenv("RENDER_TIMEOUT_SEC", "240"))
RENDER_FALLBACK = os.getenv("RENDER_FALLBACK", "1") == "1"

def r() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)

def log(*a):
    print("[worker]", *a, file=sys.stderr, flush=True)

def _sha8(txt: str) -> str:
    return hashlib.sha256(txt.encode("utf-8")).hexdigest()[:8]

def cache_key(pdf_sha: str, wm_text: str | None) -> str:
    wm_part = f"_wm_{_sha8(wm_text)}" if wm_text else ""
    return f"{pdf_sha}_d{RENDER_DPI}{wm_part}.webp"

def run(cmd: str, timeout_sec: int):
    return subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout_sec)

def render_png_with_mutool(pdf_path: str, out_png_path: str):
    cmd = f"mutool draw -F png -r {RENDER_DPI} -o {shlex.quote(out_png_path)} {shlex.quote(pdf_path)} 1"
    log("run(mutool):", cmd)
    res = run(cmd, RENDER_TIMEOUT_SEC)
    if res.returncode != 0 and not os.path.exists(out_png_path):
        raise RuntimeError(f"mutool failed ({res.returncode}): {res.stderr.decode('utf-8','ignore')}")

def png_to_webp_lossless_with_watermark(png_path: str, out_webp_path: str, wm_text: str | None):
    img = Image.open(png_path).convert("RGBA")
    if wm_text:
        # Ненавязчивая диагональная сетка ватермарок
        W, H = img.size
        overlay = Image.new("RGBA", img.size, (0,0,0,0))
        draw = ImageDraw.Draw(overlay)
        # простая метрика размера шрифта
        base = max(16, min(W, H)//18)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", base)
        except:
            font = ImageFont.load_default()

        # «плитка» — шаг по диагонали
        text = wm_text[:200]
        # полупрозрачный серый
        fill = (0,0,0,70)
        # угол
        angle = -30

        # создаём текстовый слой, чтобы поворачивать разом
        tile = Image.new("RGBA", (W, H), (0,0,0,0))
        td = ImageDraw.Draw(tile)

        # отступ по сетке
        step = int(base * 6.0)
        for y in range(-H, H*2, step):
            for x in range(-W, W*2, step):
                td.text((x, y), text, font=font, fill=fill)

        tile = tile.rotate(angle, expand=1)
        # обрежем по краям до исходного размера и смешаем
        tx, ty = (tile.size[0]-W)//2, (tile.size[1]-H)//2
        tile = tile.crop((tx, ty, tx+W, ty+H))
        img = Image.alpha_composite(img, tile)

    # сохраняем lossless WebP
    img = img.convert("RGB")
    img.save(out_webp_path, format="WEBP", lossless=True, quality=100, method=6)

def handle_render_webp(payload: dict, job_id: str) -> dict:
    pdf_sha = payload.get("pdf_sha") or ""
    local_pdf = payload.get("local_pdf") or ""
    wm_text = (payload.get("watermark_text") or "").strip() or None

    if not os.path.exists(local_pdf):
        return {"error": f"local pdf not found: {local_pdf}"}

    # кэш
    ckey = cache_key(pdf_sha, wm_text)
    cache_path = os.path.join(CACHE_DIR, ckey)

    if os.path.exists(cache_path):
        # отдаём из кэша: просто скопируем под job_id
        out_webp = os.path.join(DATA_DIR, f"{job_id}.webp")
        if os.path.exists(out_webp):
            os.remove(out_webp)
        # жёсткая ссылка/копия
        try:
            os.link(cache_path, out_webp)
        except Exception:
            import shutil; shutil.copy2(cache_path, out_webp)

        return {"pages": 1, "webp": f"{job_id}.webp", "url": f"http://127.0.0.1:8000/files/{job_id}.webp", "cache": True}

    # рендер
    with tempfile.TemporaryDirectory() as td:
        tmp_png = os.path.join(td, "p1.png")
        render_png_with_mutool(local_pdf, tmp_png)
        # watermark + webp
        tmp_webp = os.path.join(td, "p1.webp")
        png_to_webp_lossless_with_watermark(tmp_png, tmp_webp, wm_text)

        # поместим в кэш и под job_id
        out_webp = os.path.join(DATA_DIR, f"{job_id}.webp")
        import shutil
        shutil.copy2(tmp_webp, cache_path)
        shutil.copy2(tmp_webp, out_webp)

    return {"pages": 1, "webp": f"{job_id}.webp", "url": f"http://127.0.0.1:8000/files/{job_id}.webp", "cache": False}

HANDLERS = {
    "render_webp": handle_render_webp,
}

from fastapi import FastAPI
app = FastAPI(title="autopolit-v2 WORKER")

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
                res = handler(payload, job_id=job_id)
                if "error" in res:
                    raise RuntimeError(res["error"])
                client.hset(JOB_PREFIX+job_id, mapping={
                    "status":"done",
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
        return {"status":"ok","service":"worker","redis":"ok"}
    except Exception:
        return {"status":"fail","service":"worker","redis":"fail"}
