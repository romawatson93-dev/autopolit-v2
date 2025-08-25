# AGENTS.md

> **Purpose**: краткая, однозначная спецификация проекта для «агента-разработчика» (например, OpenAI Codex / автогенераторов кода) — что есть сейчас, как всё запустить локально/в Docker, какие роли и сервисы, основные API, инварианты, чек-лист изменений и правила коммитов.  
> **Статус**: активная разработка; базовый пайплайн `upload → enqueue → worker → render_webp → Redis → API /files` работает, но требует оптимизации по скорости.

--- 

## 1) Архитектура монорепо
autopolit-v2/
├─ .env # локальные переменные окружения (НЕ коммитить)
├─ .env.example # шаблон окружения
├─ docker-compose.yml # сервисы: api, worker, bot, userbot, postgres, redis
├─ CHECKPOINT.md # лог вех (prepend)
├─ scripts/ # вспомогательные PowerShell скрипты
│ ├─ http.ps1 # HTTP с обходом прокси/502
│ ├─ upload.ps1 # загрузка PDF в API (multipart)
│ ├─ smoke.ps1 # проверки /healthz и простые сценарии
│ ├─ backup.ps1 # git-тег бэкап + push
│ └─ checkpoint.ps1 # prepend-запись в CHECKPOINT.md
├─ api/
│ ├─ Dockerfile
│ ├─ requirements.txt
│ ├─ alembic.ini
│ ├─ alembic/
│ │ ├─ env.py
│ │ └─ versions/
│ │ ├─ 0001_create_clients.py
│ │ └─ 0002_add_watermark.py
│ └─ app/
│ ├─ init.py
│ ├─ main.py # FastAPI, endpoints: /healthz, /upload, /job, /clients, /files/*
│ ├─ db.py # SQLAlchemy Session, Base
│ └─ models.py # Client(id, name, watermark_text, created_at)
├─ worker/
│ ├─ Dockerfile
│ ├─ requirements.txt
│ └─ app/
│ └─ main.py # Uvicorn app с планировщиком: тянет задания из Redis, рендерит WebP
├─ bot/ # Telegram Bot (aiogram), healthz, (позже: команда «/send»)
│ ├─ Dockerfile
│ ├─ requirements.txt
│ └─ app/
│ └─ main.py
└─ userbot/ # Telethon userbot: логин-сессия, healthz
├─ Dockerfile
├─ requirements.txt
├─ login.py # интерактивный логин; кладёт *.session в /app/sessions
└─ app/
└─ main.py


**Данные и кэш** (volume `./data` внутри контейнеров):
- `/data/pdf/<sha256>.pdf` — оригиналы PDF по контент-хэшу;
- `/data/cache/<sha256>.webp` — готовые превью (lossless);
- (временный) `/tmp/<jobid>/p1.png` — промежуточный рендер (может исчезнуть).

---

## 2) Сервисы и окружение

### docker-compose (ключевые)
- **postgres**: `POSTGRES_DB=autopolit`, `POSTGRES_USER=autopolit`, `POSTGRES_PASSWORD=autopolit`
- **redis**: база 0
- **api**: FastAPI на `:8000`
- **worker**: Uvicorn на `:8001` (внешний порт), внутри слушает Redis + файловую систему
- **bot**: aiogram (порт `:8002`), позже — привязка к API
- **userbot**: Telethon (порт `:8003`), хранит `/app/sessions/*.session`

### .env.example (минимум)


APP_NAME=autopolit-v2
API_PORT=8000
WORKER_PORT=8001
BOT_PORT=8002
USERBOT_PORT=8003

DATABASE_URL=postgresql+psycopg://autopolit:autopolit@postgres:5432/autopolit
REDIS_URL=redis://redis:6379/0

Telegram

TELEGRAM_BOT_TOKEN=xxx:yyy
BOT_MODE=polling
TELETHON_API_ID=123456
TELETHON_API_HASH=xxxxxxxxxxxxxxxxxxxx
TELETHON_SESSION=/app/sessions/userbot.session

Render

RENDER_TIMEOUT_SEC=120
RENDER_DPI=300
RENDER_FALLBACK=1 # fallback на pdftoppm при проблемах с MuPDF

Files

FILES_ROOT=/data
PUBLIC_BASE=http://127.0.0.1:8000/files


---

## 3) Миграции БД (Alembic)

- **`0001_create_clients.py`** — создаёт таблицу `clients(id, name unique, created_at)`
- **`0002_add_watermark.py`** — добавляет колонку `watermark_text VARCHAR(200)`

Команды из хоста:
```powershell
docker compose exec api alembic stamp base
docker compose exec api alembic upgrade head
docker compose exec postgres sh -lc 'psql -U autopolit -d autopolit -c "\d clients"'

4) Основные API эндпоинты (FastAPI)
Health
GET /healthz  -> 200 {"status":"ok","db":"ok"}

Клиенты
POST /clients (form)
- name: str (required, unique)
- watermark_text: str (optional, <=200)
-> 200 {"id":..., "name":"...", "watermark_text":"..."}

GET /clients/{id}
-> 200 {"id":..., "name":"...", "watermark_text":"..."}

Загрузка PDF и постановка задачи
POST /upload (multipart/form-data)
- file: application/pdf (required)
- client_id: int (optional, если указан — worker применит watermark_text)
-> 200 {"job_id":"<uuid>", "queued":true}

Статус задания
GET /job/{job_id}
-> {"exists":true, "status":"processing"|"done"|"error", "kind":"render_webp", "result":{...}?, "error": "..."}
# При done.result:
# { "pages": 1, "webp": "<job_id>.webp", "url": "http://127.0.0.1:8000/files/<job_id>.webp" }

Выдача артефактов
GET /files/{name}
# отдаёт с диска из $FILES_ROOT (read-only)

5) Worker: алгоритм рендера (WebP, кэш, ватермарка)

Кэш по контент-хэшу: при upload API читает файл, считает SHA256 и сохраняет как /data/pdf/<sha256>.pdf.
Job содержит: job_id, pdf_sha, client_id?.

Рендер первой страницы (быстро и качественно):

Путь А (основной): mutool draw -F png -r $RENDER_DPI -o /tmp/<job>/p1.png /data/pdf/<sha256>.pdf 1

Применить ватермарку (Pillow): полупрозрачный текст из clients.watermark_text (если есть), паттерном по диагонали, не мешающий чтению.

Сохранение в WebP (lossless): p1.png → /data/cache/<sha256>.webp с lossless=True, quality=100, method=6.

Ответ в Redis: статус done, url = $PUBLIC_BASE/<job_id>.webp.
Физически файл копируется/сохраняется как /data/<job_id>.webp.

Fallback (если MuPDF > таймаут/ошибка): pdftoppm -singlefile -png -f 1 -l 1 -r 144 → затем тот же pipeline → WebP.

Параллелизм по страницам — TODO (когда перейдём к многостраничной выдаче).

Тонкая настройка MuPDF — TODO: параметры антиалиасинга/субпикселей.

6) Взаимодействие с Telegram

bot/: aiogram, healthz OK; позже добавим команду /render.

userbot/: Telethon, интерактивный login.py:

docker compose exec -it userbot python login.py


создаст /app/sessions/userbot.session.

7) Запуск локально (Windows + PowerShell)
# заполнить .env
docker compose up -d --build

# миграции
docker compose exec api alembic stamp base
docker compose exec api alembic upgrade head

# healthz
.\scripts\http.ps1 -Url "http://127.0.0.1:8000/healthz" -Container api -InternalUrl "http://127.0.0.1:8000/healthz"

# клиент
docker compose exec worker sh -lc "python - <<'PY'
import requests
r = requests.post('http://api:8000/clients', data={'name':'Acme Ltd','watermark_text':'Итоговая стоимость 325850р'})
print(r.status_code, r.text)
PY"

8) Инварианты и правила

Не изменять формат API без явного описания.

Не коммитить секреты.

Миграции — последовательные, с down_revision.

Код-стайл: ruff/black.

Коммиты: feat:, fix:, docs:, chore: и т.д.

Проверка: scripts/smoke.ps1.

9) План ускорения (≤ 30 s)

Кэш по SHA256.

Параллельный рендер страниц.

Тюнинг MuPDF.

Строгий таймаут subprocess.

Асинхронные очереди (позже — rq/celery).

Ватермарка — полупрозрачная, ≤80 символов.

10) Изменения API (journal)

v0.1:

POST /upload

GET /job/{id}

POST /clients

GET /files/{name}

11) Частые команды
docker compose up -d --build api worker
docker compose logs -f api
docker compose exec worker sh
docker compose exec worker sh -lc 'echo DPI=$RENDER_DPI TIMEOUT=$RENDER_TIMEOUT_SEC FALLBACK=$RENDER_FALLBACK'

12) TODO / Backlog

Многостраничный рендер.

Параллелизм worker.

Настройки ватермарки.

Интеграция bot/userbot.

TTL ссылки.

CI/CD.

Метрики.
## 13) Контакты и роли
- **Product/owner**: Roma  
- **Agent**: Codex/OpenAI  
- Правила: не ломать API, новые параметры — через `.env.example`, каждый коммит фиксировать в `CHECKPOINT.md`.
