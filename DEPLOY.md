# 🚀 Деплой на Railway — Souldawn Dating

Пошаговое руководство для запуска всех 3 сервисов (API + Bot + Web) на Railway.

---

## 📋 Что нужно подготовить

1. **Аккаунт Railway** — https://railway.app (есть free trial $5)
2. **Bot Token** — от [@BotFather](https://t.me/BotFather) в Telegram
3. **Zhipu AI ключ** — https://open.bigmodel.cn (для GLM-5.2)
4. **Cloudflare R2** (опционально для фото) — https://dash.cloudflare.com
5. **GitHub репозиторий** — запушить папку `dating/`

---

## Шаг 0: Подготовка кода

```bash
cd /Users/hellcart/ZCodeProject/dating

# Инициализируй отдельный git-репозиторий для dating-проекта
git init
git add .
git commit -m "feat: initial dating app — api + bot + web"

# Запушь на GitHub в отдельный репозиторий
# (или можешь использовать monorepo — Railway умеет subdir)
gh repo create souldawn-dating --private --source=. --push
```

---

## Шаг 1: Создать проект на Railway

1. Зайди на https://railway.app → **New Project**
2. Выбери **Deploy from GitHub repo** → выбери свой репозиторий
3. Railway создаст проект — мы добавим в него 3 сервиса

---

## Шаг 2: Добавить PostgreSQL

1. В проекте Railway → **New → Database → PostgreSQL**
2. Railway создаст БД и выдаст переменную `DATABASE_URL`
3. **Важно**: формат будет `postgresql://...` — его нужно конвертировать для Python:
   - Для API/Bot: `postgresql+asyncpg://...` (добавить `+asyncpg`)
   - Web это не нужно

---

## Шаг 3: Добавить Redis

1. **New → Database → Redis**
2. Railway выдаст `REDIS_URL` (формат `redis://...`)

---

## Шаг 4: Деплой API (FastAPI)

1. **New → GitHub Repo → выбрать тот же репо**
2. В настройках сервиса:
   - **Root Directory**: `api`
   - Railway сам найдёт `Dockerfile`
3. Перейди в **Variables** и добавь:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` (от Railway PostgreSQL, добавь `+asyncpg`) |
| `REDIS_URL` | `redis://...` (от Railway Redis) |
| `JWT_SECRET` | случайная строка 64 символа (`openssl rand -hex 32`) |
| `BOT_TOKEN` | твой токен от BotFather |
| `ADMIN_IDS` | твой Telegram ID (узнать у @userinfobot) |
| `ZHIPU_API_KEY` | ключ от open.bigmodel.cn |
| `R2_ACCOUNT_ID` | (опц.) Cloudflare account ID |
| `R2_ACCESS_KEY_ID` | (опц.) R2 access key |
| `R2_SECRET_ACCESS_KEY` | (опц.) R2 secret |
| `R2_BUCKET_NAME` | `souldawn-dating` |
| `R2_PUBLIC_URL` | `https://media.yourdomain.com` |

4. Railway задеплоит → проверь **Logs**, дождись `Application startup complete`
5. **Settings → Networking → Generate Domain** → получишь `https://api.xxx.up.railway.app`
6. Проверь: открой `https://api.xxx.up.railway.app/health` → должно вернуть `{"status":"ok"}`

---

## Шаг 5: Создать администратора

После деплоя API, создай супер-админа через Railway Console:

1. В сервисе **api** → **Settings → Command** → временно измени startCommand на:
   ```
   python seed_admin.py --telegram-id ВАШ_TG_ID --name "Ваше Имя"
   ```
2. Railway перезапустит, в логах увидишь: `[OK] Admin user created`
3. Верни оригинальный startCommand: `uvicorn main:app --host 0.0.0.0 --port $PORT --workers 1`

**Альтернатива**: подключиться к PostgreSQL и выполнить SQL напрямую.

---

## Шаг 6: Деплой Bot (aiogram)

1. **New → GitHub Repo → тот же репо**
2. **Root Directory**: `bot`
3. **Variables**:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` (то же что у API) |
| `REDIS_URL` | `redis://...` |
| `BOT_TOKEN` | токен бота |
| `BOT_USERNAME` | `souldawn_dating_bot` (без @) |
| `ADMIN_IDS` | твой Telegram ID |
| `API_BASE_URL` | `https://api.xxx.up.railway.app` |
| `SITE_URL` | `https://web.xxx.up.railway.app` (после шага 7) |

4. Railway задеплоит → в логах должно быть: `Souldawn Dating Bot @xxx started!`
5. Напиши боту `/start` — должен ответить приветствием

---

## Шаг 7: Деплой Web (React)

1. **New → GitHub Repo → тот же репо**
2. **Root Directory**: `web`
3. **Variables** (эти `VITE_` переменные встраиваются при сборке):

| Variable | Value |
|---|---|
| `VITE_API_URL` | `https://api.xxx.up.railway.app` |
| `VITE_BOT_USERNAME` | `souldawn_dating_bot` |

4. Railway задеплоит → **Generate Domain** → `https://web.xxx.up.railway.app`
5. Открой сайт — должен показать лендинг

---

## Шаг 8: Настроить Telegram Mini App

1. В [@BotFather](https://t.me/BotFather) → `/mybots` → выбери бота
2. **Bot Settings → Menu Button → Configure menu button**
3. Укажи URL: `https://web.xxx.up.railway.app/discover`
4. Теперь у бота появится кнопка меню, открывающая Mini App

---

## Шаг 9: Тестирование

```bash
# Проверь API health
curl https://api.xxx.up.railway.app/health

# Проверь API docs (Swagger UI)
open https://api.xxx.up.railway.app/docs

# Зайди в админку
# Открой: https://web.xxx.up.railway.app/admin
```

---

## 🔧 Локальная разработка

Пока сервисы на Railway, можно разрабатывать локально:

```bash
# 1. Подними только БД и Redis
docker compose up -d postgres redis

# 2. API (в отдельном терминале)
cd api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# 3. Бот
cd bot
pip install -r requirements.txt
python bot.py

# 4. Веб
cd web
npm install
npm run dev
```

---

## 🚨 Частые проблемы

### Бот не отвечает
- Проверь `BOT_TOKEN` в Variables
- В Logs должно быть `started!` — если нет, Bot Token невалидный

### API возвращает 500
- Проверь `DATABASE_URL` — должен быть `postgresql+asyncpg://`
- В Logs ищи `PostgreSQL connected` — если нет, БД недоступна

### Web показывает белый экран
- Проверь `VITE_API_URL` — должен быть публичный URL API
- Открой DevTools → Console — ищи ошибки CORS

### Мэтчи не приходят в реал-тайм
- Проверь `REDIS_URL` у всех 3 сервисов — должен быть одинаковый
- В Logs API должно быть `Redis connected successfully`

### Бот теряет FSM-состояние
- Уже исправлено: бот теперь использует RedisStorage (см. `bot.py:get_fsm_storage()`)
- Убедись что `REDIS_URL` указан

---

## 💰 Оценка стоимости Railway

| Сервис | Память | Цена/мес |
|---|---|---|
| PostgreSQL | ~512MB | $5 |
| Redis | ~128MB | $2 |
| API (FastAPI) | ~256MB | $3 |
| Bot (aiogram) | ~128MB | $2 |
| Web (static) | ~64MB | $1 |
| **Итого** | | **~$13/мес** |

Free trial даёт $5 — хватит на первую неделю тестирования.

---

## 🌐 Кастомный домен (опционально)

1. Railway → сервис web → **Settings → Networking → Custom Domain**
2. Добавь `dating.yourdomain.com`
3. У DNS-провайдера добавь CNAME → `xxx.up.railway.app`
4. То же для API: `api.yourdomain.com`

---

## ✅ Чек-лист готовности

- [ ] PostgreSQL добавлен, `DATABASE_URL` скопирован
- [ ] Redis добавлен, `REDIS_URL` скопирован
- [ ] API задеплоен, `/health` отвечает
- [ ] `seed_admin.py` запущен, админ создан
- [ ] Bot задеплоен, отвечает на `/start`
- [ ] Web задеплоен, лендинг открывается
- [ ] `VITE_API_URL` указан для Web
- [ ] Mini App кнопка настроена в BotFather
- [ ] Telegram Login работает (автологин из TMA)
- [ ] Свайпы работают, мэтчи создаются
- [ ] Админка `/admin` доступна
