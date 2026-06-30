# 💕 Souldawn Dating

Сервис знакомств нового поколения. Объединяет механику «Леонардо Дайвинчик» (ТГ-бот) с Tinder-подобным UI (Web/iOS), дополненный AI-мэтчами на базе GLM-5.2.

## Архитектура

```
Telegram Bot (aiogram)  ←→  Redis Pub/Sub  ←→  FastAPI Backend  ←→  PostgreSQL
                                    ↕                            ↕
                              Bot: мэтчи/уведомления       Cloudflare R2 (фото)
                                    ↕
React Frontend (Vite) ←→  WebSocket (real-time чат)
  ├─ Web PWA (браузер)
  ├─ Telegram Mini App
  └─ iOS App (Capacitor)
```

## Стек

| Слой | Технология |
|---|---|
| Бот | Python 3.12 + aiogram 3 + SQLAlchemy async |
| API | FastAPI + Pydantic v2 + WebSocket |
| Real-time | Redis Pub/Sub |
| Frontend | React 19 + Vite + Tailwind 4 + Framer Motion |
| БД | PostgreSQL 16 |
| Медиа | Cloudflare R2 |
| AI | Zhipu AI (GLM-4v / GLM-4) — модерация + мэтчинг |
| iOS | Capacitor.js |
| Хостинг | Railway (bot + api + web) |

## Быстрый старт

### 1. Скопируй env
```bash
cp .env.example .env
# Заполни BOT_TOKEN (от @BotFather), ZHIPU_API_KEY, R2 ключи
```

### 2. Запусти через Docker Compose
```bash
docker compose up -d
```
Это поднимет: PostgreSQL, Redis, API (:8000), Бот, Web (:5173).

### 3. Применить миграции БД
```bash
cd prisma
npx prisma db push
```

### 4. Открой
- **Web**: http://localhost:5173
- **API docs**: http://localhost:8000/docs
- **Бот**: напиши `/start` в Telegram

## Без Docker (локальная разработка)

### PostgreSQL + Redis
```bash
docker compose up -d postgres redis
```

### API Backend
```bash
cd api
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Telegram Bot
```bash
cd bot
pip install -r requirements.txt
python bot.py
```

### React Frontend
```bash
cd web
npm install
npm run dev
```

## Структура

```
dating/
├── docker-compose.yml
├── prisma/schema.prisma      # 9 моделей (source of truth)
├── bot/                      # Telegram-бот
│   ├── bot.py               # Entry point
│   ├── config.py            # Env vars
│   ├── database/            # SQLAlchemy ORM + CRUD
│   ├── handlers/            # registration, dating, matches
│   ├── middlewares/         # auto-registration
│   ├── services/            # Redis subscriber
│   ├── keyboards.py         # Inline keyboards
│   ├── states.py            # FSM states
│   └── texts.py             # Messages
├── api/                      # FastAPI backend
│   ├── main.py              # App + CORS + lifespan
│   ├── database/            # Async session factory
│   ├── models/              # SQLAlchemy ORM + Pydantic schemas
│   ├── routers/             # auth, profiles, likes, matches, chat, upload, report
│   ├── services/            # ai_matchmaker, ai_moderation, matching, r2_storage, realtime
│   └── middleware/          # JWT auth dependency
└── web/                      # React SPA
    ├── src/
    │   ├── App.tsx          # Router + BottomNav
    │   ├── pages/           # Login, Onboarding, Discover, Matches, Chat, Profile
    │   ├── components/      # SwipeCard, SwipeDeck, MatchModal
    │   ├── lib/             # api.ts, websocket.ts, telegram.ts, store.ts
    │   └── styles/           # Tailwind globals
    ├── capacitor.config.ts   # iOS обёртка
    └── public/              # manifest.json, sw.js
```

## AI-фичи (GLM-5.2)

### AI Matchmaker (`api/services/ai_matchmaker.py`)
- При создании мэтча — GLM-4 анализирует обе анкеты
- Скоринг совместимости 0-100 + текстовое объяснение
- Fallback: простой алгоритм по общим интересам

### AI Модерация (`api/services/ai_moderation.py`)
- Проверка текста (bio) через GLM-4 — блокировка NSFW/спам/мошенничество
- Проверка фото через GLM-4V (multimodal) — блокировка nudity/weapon/drugs
- Авто-бан при 3+ жалобах от пользователей

## App Store Submission Checklist

- [ ] Apple Sign-In (требование 4.8 при наличии сторонней авторизации)
- [ ] Кнопка «Пожаловаться/Заблокировать» в каждом профиле и чате
- [ ] Content Moderation Policy URL
- [ ] Возрастной рейтинг 17+ (Dating)
- [ ] Privacy Policy URL
- [ ] Terms of Service URL
- [ ] Уведомление о покупке Premium до транзакции
- [ ] TestFlight бета-тестирование (минимум 2 недели)
- [ ] Скриншоты для iPhone 15 Pro Max, iPad Pro
- [ ] Отчёт о контент-модерации

## Данные для .

| Переменная | Где взять |
|---|---|
| `BOT_TOKEN` | @BotFather в Telegram |
| `ZHIPU_API_KEY` | https://open.bigmodel.cn |
| `R2_*` | Cloudflare Dashboard → R2 |
| `STRIPE_*` | https://dashboard.stripe.com (Premium) |
| `APPLE_*` | Apple Developer Portal |
