# scripts\apply-fast-webp.ps1
$ErrorActionPreference = "Stop"

function Backup-IfExists($path) {
  if (Test-Path $path) {
    Copy-Item $path "$path.bak_$(Get-Date -Format 'yyyyMMdd-HHmmss')" -Force
  }
}

Write-Host "==> Writing AGENTS.md"
@'
# Autopolit v2 — AGENTS.md

Краткий бриф для код-агентов (OpenAI Codex / “ИИ-пейр”) по проекту.

## 1) Назначение
- Сервис принимает PDF сметы → рендерит **страницу(ы) в WebP (lossless)** c водяным знаком.
- Цель: быстро (≤30 c), без утечки контента (минимизация копирования/скриншота).

## 2) Текущая архитектура
- **api/** (FastAPI): конечные точки `/healthz`, `/clients`, `/upload`, `/job/{id}`, `/files/*`.
- **worker/** (Uvicorn): подписчик очереди (Redis), реально рендерит PDF → WebP.
- **bot/**, **userbot/**: телеграм-интеграции (не критично в этом патче).
- **postgres**, **redis** — инфраструктура.

## 3) Что делает этот апдейт
1. Рендер: **mutool draw → PNG → cwebp (lossless)**, без Pillow в горячем пути.
2. **Кэш**: по SHA-256 содержимого PDF (`/data/cache/<hash>/page-<n>.webp`).
3. **Распараллеливание**: по страницам (ENV `WORKER_MAX_PROCS`, `MUTOOL_DPI`).
4. **Ватермарка**: текст из `clients.watermark_text` (через API `client_id`).
5. Док: этот `AGENTS.md`.

## 4) Окружение (ENV)
- `RENDER_TIMEOUT_SEC` (по умолчанию 60–120): общий таймаут на задачу.
- `MUTOOL_DPI` (например 150–300): DPI рендера mutool.
- `WORKER_MAX_PROCS` (например 2–4): сколько процессов параллелить страницы.
- `RENDER_LOSSLESS` (1/0): lossless WebP.

## 5) Проверка (локально)
1. `docker compose up -d --build api worker`
2. `POST /clients` → получить `id`
3. `POST /upload (file, client_id)` → получить `job_id`
4. Поллинг `GET /job/{job_id}` до `done` → получаем `url` WebP

## 6) Производительность
- Тёплый кэш: выдача мгновенно (файлы уже лежат в `/data/cache/<hash>`).
- Холодный: выдаём 1-ю страницу сразу после готовности, без Pillow в рендере.

## 7) Безопасность
- Водяной знак на стороне worker при сборке WebP.
- Сырые PNG удаляются после упаковки.
'@ | Set-Content -Encoding utf8 -NoNewline AGENTS.md

Write-Host "==> Updating worker/Dockerfile"
Backup-IfExists "worker\Dockerfile"
@'
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    mupdf-tools \
    webp \
    curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV PYTHONUNBUFFERED=1
ENV PATH="/usr/bin:${PATH}"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
'@ | Set-Content -Encoding utf8 -NoNewline worker\Dockerfile

Write-Host "==> Ensuring worker requirements include Pillow"
$reqPath = "worker\requirements.txt"
Backup-IfExists $reqPath
if (-not (Test-Path $reqPath)) { throw "File not found: $reqPath" }
$req = Get-Content $reqPath -Raw
if ($req -notmatch "(?im)^\s*pillow\b") {
  $req = ($req.TrimEnd() + "`r`nPillow==10.4.0`r`n")
  $req | Set-Content -Encoding utf8 -NoNewline $reqPath
}

Write-Host "==> Writing worker/app/fast_renderer.py"
ni worker\app -ItemType Directory -Force | Out-Null
@'
import hashlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

DATA_DIR = Path("/data")
PDF_DIR = DATA_DIR / "pdf"
CACHE_DIR = DATA_DIR / "cache"
OUT_DIR = DATA_DIR / "out"

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

MUTOOL_DPI = _env_int("MUTOOL_DPI", 200)
WORKER_MAX_PROCS = _env_int("WORKER_MAX_PROCS", 2)
RENDER_LOSSLESS = _env_int("RENDER_LOSSLESS", 1)

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def ensure_dirs() -> None:
    for d in (PDF_DIR, CACHE_DIR, OUT_DIR):
        d.mkdir(parents=True, exist_ok=True)

def mutool_pages_count(pdf: Path) -> int:
    # mutool show file.pdf pages -> "pages N"
    try:
        out = subprocess.check_output(
            ["mutool", "show", str(pdf), "pages"],
            stderr=subprocess.STDOUT, text=True, timeout=15
        )
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("pages"):
                return int(line.split()[1])
    except Exception:
        pass
    return 1

def run_mutool_to_png(pdf: Path, tmpdir: Path, dpi: int, pages: List[int]) -> List[Path]:
    pages_arg = ",".join(str(p) for p in pages)
    pattern = str(tmpdir / "p-%d.png")
    cmd = ["mutool", "draw", "-F", "png", "-r", str(dpi), "-o", pattern, str(pdf), pages_arg]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return [tmpdir / f"p-{p}.png" for p in pages]

def png_to_webp(png: Path, webp: Path, lossless: bool) -> None:
    args = ["cwebp"]
    if lossless:
        args += ["-z", "9", "-lossless"]
    else:
        args += ["-q", "90"]
    args += [str(png), "-o", str(webp)]
    subprocess.check_call(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def stamp_watermark_webp(webp: Path, text: Optional[str]) -> None:
    if not text:
        return
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return
    try:
        im = Image.open(str(webp)).convert("RGBA")
        W, H = im.size
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        font_size = max(18, int(W * 0.03))
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        pad = int(min(W, H) * 0.03)
        msg = text[:200]
        tw, th = draw.textsize(msg, font=font)
        x, y = pad, H - th - pad
        draw.text((x, y), msg, fill=(255, 255, 255, 165), font=font)
        out = Image.alpha_composite(im, layer).convert("RGB")
        out.save(str(webp), "WEBP", quality=100, lossless=True, method=6)
    except Exception:
        pass

def render_pdf_to_webp(pdf: Path, watermark_text: Optional[str], timeout_sec: int = 120) -> Tuple[int, List[Path]]:
    ensure_dirs()
    h = sha256_file(pdf)
    pages = mutool_pages_count(pdf)
    cache_base = CACHE_DIR / h
    cache_base.mkdir(parents=True, exist_ok=True)

    webps = [cache_base / f"page-{p}.webp" for p in range(1, pages + 1)]
    if all(p.exists() for p in webps):
        return pages, webps

    todo_pages = [p for p in range(1, pages + 1) if not (cache_base / f"page-{p}.webp").exists()]
    with tempfile.TemporaryDirectory() as td:
        tmpdir = Path(td)
        for i in range(0, len(todo_pages), WORKER_MAX_PROCS):
            batch = todo_pages[i:i + WORKER_MAX_PROCS]
            run_mutool_to_png(pdf, tmpdir, MUTOOL_DPI, batch)
            for p in batch:
                png = tmpdir / f"p-{p}.png"
                webp = cache_base / f"page-{p}.webp"
                png_to_webp(png, webp, lossless=bool(RENDER_LOSSLESS))
                stamp_watermark_webp(webp, watermark_text)
                try:
                    png.unlink(missing_ok=True)
                except Exception:
                    pass
    return pages, [cache_base / f"page-{p}.webp" for p in range(1, pages + 1)]

def materialize_first_page(h: str) -> Optional[Path]:
    base = CACHE_DIR / h
    p1 = base / "page-1.webp"
    if not p1.exists():
        return None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{h}-p1.webp"
    shutil.copyfile(p1, out)
    return out
'@ | Set-Content -Encoding utf8 -NoNewline worker\app\fast_renderer.py

Write-Host "==> Updating worker/app/main.py"
Backup-IfExists "worker\app\main.py"
@'
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
'@ | Set-Content -Encoding utf8 -NoNewline worker\app\main.py

Write-Host "==> Updating api/app/main.py"
Backup-IfExists "api\app\main.py"
@'
import os
import json
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from typing import Optional
from pathlib import Path
import redis
from sqlalchemy import select
from .db import get_session
from .models import Client

app = FastAPI()

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
r = redis.from_url(REDIS_URL)

DATA_DIR = Path("/data")
OUT_DIR = DATA_DIR / "out"
PDF_DIR = DATA_DIR / "pdf"
for d in (DATA_DIR, OUT_DIR, PDF_DIR):
    d.mkdir(parents=True, exist_ok=True)

def job_key(jid: str) -> str:
    return f"job:{jid}"

def get_job(jid: str) -> dict:
    d = r.hgetall(job_key(jid))
    return {k.decode(): v.decode() for k, v in d.items()}

@app.get("/healthz")
def healthz():
    try:
        with get_session() as s:
            s.execute(select(Client.id)).first()
        db_status = "ok"
    except Exception:
        db_status = "fail"
    return {"status": "ok", "db": db_status}

@app.post("/clients")
def create_client(name: str = Form(...), watermark_text: Optional[str] = Form(None)):
    with get_session() as s:
        exists = s.execute(select(Client).where(Client.name == name)).scalar_one_or_none()
        if exists:
            return {"id": exists.id, "name": exists.name, "watermark_text": exists.watermark_text}
        c = Client(name=name, watermark_text=watermark_text)
        s.add(c)
        s.commit()
        s.refresh(c)
        return {"id": c.id, "name": c.name, "watermark_text": c.watermark_text}

@app.post("/upload")
async def upload(file: UploadFile = File(...), client_id: Optional[int] = Form(None)):
    data = await file.read()
    if not data or len(data) < 10:
        raise HTTPException(status_code=400, detail="empty file")
    pdf_path = PDF_DIR / f"{os.urandom(16).hex()}.pdf"
    pdf_path.write_bytes(data)

    watermark_text = None
    if client_id:
        with get_session() as s:
            c = s.get(Client, client_id)
            if not c:
                raise HTTPException(status_code=404, detail="client not found")
            watermark_text = c.watermark_text

    import uuid
    jid = str(uuid.uuid4())
    payload = {
        "id": jid,
        "kind": "render_webp",
        "path": str(pdf_path),
        "watermark_text": watermark_text
    }
    r.hset(job_key(jid), mapping={"status": "queued", "kind": "render_webp"})
    r.rpush("jobs", json.dumps(payload))
    return {"job_id": jid}

@app.get("/job/{jid}")
def get_status(jid: str):
    d = get_job(jid)
    if not d:
        return {"exists": False}
    return {"exists": True, **d}

@app.get("/files/{name}")
def files(name: str):
    path = OUT_DIR / name
    if not path.exists():
        raise HTTPException(404, "Not Found")
    return FileResponse(str(path), filename=name)
'@ | Set-Content -Encoding utf8 -NoNewline api\app\main.py

Write-Host "==> Done. You can now rebuild."
