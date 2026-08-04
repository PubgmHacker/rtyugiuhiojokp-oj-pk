# 💕 Souldawn

Сервис знакомств: Telegram-бот с простотой «Дайвинчика», Telegram Mini App
и iOS-приложение с современным интерфейсом, плюс лендинг с юридическими
страницами.

```
Telegram Bot (aiogram 3) ←→ Redis Pub/Sub ←→ FastAPI ←→ PostgreSQL 16
                                  ↕                        ↕
                          уведомления о мэтчах      Cloudflare R2 (фото)
                                  ↕
React 19 + Vite ←→ WebSocket (чат)
  ├─ Web PWA
  ├─ Telegram Mini App
  └─ iOS (Capacitor 8)

landing/ — статический сайт и юридические документы
```

## Стек

| Слой | Технология |
|---|---|
| Бот | Python 3.12 + aiogram 3 + SQLAlchemy async |
| API | FastAPI + Pydantic v2 + WebSocket |
| Real-time | Redis Pub/Sub |
| Фронтенд | React 19 + Vite 6 + Tailwind 4 + Framer Motion + zustand |
| БД | PostgreSQL 16, миграции через Alembic |
| Медиа | Cloudflare R2 |
| AI | Zhipu GLM — модерация контента и скоринг совместимости |
| iOS | Capacitor 8 (Swift Package Manager), Xcode 16+ |
| Лендинг | Статика: HTML + CSS + ванильный JS |
| Хостинг | Railway (bot + api + web) |

## Быстрый старт

```bash
cp .env.example .env      # заполните BOT_TOKEN, ZHIPU_API_KEY, R2_*
docker compose up -d      # PostgreSQL, Redis, API :8000, бот, веб :5173
cd api && alembic upgrade head
```

- Веб: http://localhost:5173
- Документация API: http://localhost:8000/docs (только при `DEBUG=true`)
- Бот: напишите `/start`
- Лендинг: `cd landing && python3 -m http.server 8000`

Без `BOT_TOKEN` / `ZHIPU_API_KEY` / `R2_*` проект тоже запускается:
проверка initData отключается, модерация переходит на словарный фильтр,
фото остаются как `file_id` Telegram.

## Локальная разработка без Docker

```bash
docker compose up -d postgres redis

cd api && pip install -r requirements.txt && uvicorn main:app --reload --port 8000
cd bot && pip install -r requirements.txt && python bot.py
cd web && npm install && npm run dev
```

## iOS

```bash
./tools/ios-build.sh simulator   # проверка сборки
./tools/ios-build.sh open        # открыть в Xcode
DEVELOPMENT_TEAM=XXXXXXXXXX ./tools/ios-build.sh archive   # релиз
```

Capacitor CLI требует Node ≥ 22 — скрипт сам находит подходящую версию,
если основная в системе старее. Публикация, разбор рисков ревью и
чек-лист — в [APPSTORE.md](APPSTORE.md).

Иконки и splash генерируются из кода:

```bash
python3 tools/make_icons.py
```

## Что умеет

**Бот** — регистрация за 7 коротких шагов с кнопкой «Назад», просмотр
анкет с `❤️`/`👎`, взаимный лайк с уведомлением обеим сторонам, жалоба с
выбором причины, пауза показа анкеты, удаление аккаунта, Premium за
Telegram Stars, реферальный буст.

**Mini App и веб** — свайп-дека с пружинной физикой и подсветкой жеста,
шторка фильтров, экран взаимной симпатии, чат по WebSocket с
переподключением и дедупликацией, «кто меня лайкнул», профиль с
удалением аккаунта.

**Кросс-платформенность** — сообщение из веба уходит пушем в Telegram,
лайк из веба приходит в бота с кнопками. Аккаунт один.

**Безопасность** — модерация фото и текста до публикации в обоих каналах
регистрации, жалоба в один тап, эскалация по числу разных жалобщиков
(3 — скрытие анкеты, 5 — автобан), строго 18+.

## Структура

```
souldawn-dating/
├── bot/                    # Telegram-бот
│   ├── handlers/           # registration, dating, matches, premium,
│   │                       # referral, account (меню, пауза, удаление)
│   ├── middlewares/        # авторегистрация, антифлуд
│   ├── services/           # модерация, R2, Redis-подписчик, CryptoBot
│   └── texts.py            # все пользовательские строки
├── api/                    # FastAPI
│   ├── routers/            # auth, profiles, likes, matches, chat,
│   │                       # upload, report, admin
│   ├── services/           # ai_matchmaker, ai_moderation, matching,
│   │                       # r2_storage, realtime
│   ├── migrations/         # ревизии Alembic
│   └── tests/              # smoke-тесты
├── web/                    # React SPA
│   ├── src/components/     # ui.tsx (примитивы), SwipeCard, SwipeDeck,
│   │                       # MatchModal
│   ├── src/lib/            # api, store, websocket, telegram,
│   │                       # haptics, native
│   ├── src/styles/         # globals.css — дизайн-система
│   └── ios/                # нативный проект Capacitor
├── landing/                # лендинг и юридические страницы
├── tools/                  # make_icons.py, ios-build.sh
├── prisma/schema.prisma    # описание схемы БД
├── APPSTORE.md             # публикация в App Store
└── DEPLOY.md               # деплой и миграции
```

## Дизайн-система

Единый источник токенов — `web/src/styles/globals.css`. Лендинг
повторяет те же значения вручную, поскольку собирается без тулчейна.

- Фон `#0b0a12`, поверхности `#191725` / `#221f31`
- Бренд-градиент «рассвет»: `#ff3d71 → #ff5c7a → #ff7a5c → #ffc46b`
- Акцент `#ff3d71`, успех `#2ee6a8`, верификация `#4da3ff`
- Шрифт Inter, крупные заголовки с `letter-spacing: -0.035em`
- Скругления: карточки 28px, плитки 18px
- Liquid Glass: `blur(24px) saturate(180%)` поверх `rgb(255 255 255 / 0.07)`
- Движение: пружина `stiffness 380 / damping 34`, уважается
  `prefers-reduced-motion`

Экраны собираются из примитивов `web/src/components/ui.tsx` — `Button`,
`IconButton`, `Chip`, `Card`, `Skeleton`, `EmptyState`, `ScreenHeader`,
`VerifiedBadge`, `Spinner`. Хардкодить цвета в компонентах не нужно.

## Переменные окружения

| Переменная | Где взять |
|---|---|
| `BOT_TOKEN` | @BotFather |
| `ZHIPU_API_KEY` | https://open.bigmodel.cn — без него модерация по словарю |
| `R2_*` | Cloudflare Dashboard → R2 |
| `DATABASE_URL`, `REDIS_URL` | Railway или локальный docker compose |
| `CORS_ORIGINS` | Домены фронтенда, через запятую |
| `DEBUG` | `false` в проде: закрывает `/docs` и гостевой вход |

Полный список с комментариями — в `.env.example`.

## Проверка перед пушем

```bash
cd web && npx tsc -b && npm run build
cd api && python -m compileall -q . && python -m pytest tests/ -q
cd bot && python -m compileall -q .
./tools/ios-build.sh simulator
```
