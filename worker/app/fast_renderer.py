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