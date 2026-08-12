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

**Мессенджер сверх базового чата** — истории на 24 часа с ответом
сообщением в пару, темы переписки на двоих (пресеты, свои цвета и узоры
с Plus), серия общения с восстановлением, план дня прямо в чате
(задачи-привычки), комнаты по интересам, пересылка рилсов, айсбрейкеры.

**Персонализация и монетизация** — семь схем оформления приложения
(две платные), рамки карточки за коллекцию наклеек из кейсов, три
тарифа + Telegram Stars и App Store IAP, подписка в подарок одноразовым
кодом с защитой от повторного чека.

**Кросс-платформенность** — сообщение из веба уходит пушем в Telegram,
лайк из веба приходит в бота с кнопками. Аккаунт один. В нативном
iOS-приложении вход по одноразовому коду: `/link` в боте выдаёт код,
приложение обменивает его на сессию.

**Безопасность** — модерация фото и текста до публикации в обоих каналах
регистрации, жалоба в один тап, эскалация по числу разных жалобщиков
(3 — скрытие анкеты, 5 — автобан) и только от тех, кто реально
пересекался с целью. Блокировка пользователя необратима: пара исчезает
из выдачи друг друга навсегда. Фото перекодируются перед загрузкой —
EXIF с GPS-координатами не попадает в публичное хранилище. Строго 18+.

## Структура

```
souldawn-dating/
├── bot/                    # Telegram-бот
│   ├── handlers/           # registration, dating, matches, premium,
│   │                       # referral, account (меню, пауза, удаление)
│   ├── middlewares/        # авторегистрация, антифлуд
│   ├── services/           # модерация, R2, Redis-подписчик, CryptoBot,
│   │                       # link_codes (коды входа в приложение)
│   └── texts.py            # все пользовательские строки
├── api/                    # FastAPI
│   ├── routers/            # auth, profiles, likes, matches, chat,
│   │                       # upload, report, blocks, admin
│   ├── services/           # ai_matchmaker, ai_moderation, matching,
│   │                       # r2_storage, realtime, image_sanitizer,
│   │                       # link_codes
│   ├── migrations/         # ревизии Alembic
│   └── tests/              # smoke-тесты и тесты правок по аудиту
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
повторяет те же значения вручную, поскольку собирается без тулчейна;
расхождение ловит тест `test_лендинг_и_миниапп_не_расходятся_по_палитре`.

Главный принцип: **название продукта — случайное слово, дизайн из него
не выводится**. Никаких рассветов, закатов и «души» ни в палитре, ни в
метафорах, ни в именах утилит. Второй принцип: цветом обозначаем только
действие и статус, всё остальное — оттенки серого. Внимание должно
доставаться фотографиям людей, а не интерфейсу.

- Фон `#0a0b0f`, поверхности `#16181f` / `#1c1f28` / `#252935` —
  холодная нейтральная база, близкая к системному тёмному iOS
- Акцент `#ff2d6f` — одна малина на все главные действия (4.5:1 на
  фоне, белый глиф на заливке 4.6:1). Плоская заливка через штатные
  `bg-accent` / `bg-accent-soft`, без градиентов и цветных свечений
- Текст четырьмя ступенями: `#fafbfc` / `#c8cdd4` / `#9ba1ab` /
  `#868d96`, все проходят AA на базовом фоне
- Семантика: лайк `#34d399`, опасность `#ff7a1a` (отодвинута от акцента
  на 25° — «ошибка» не должна читаться как главное действие),
  предупреждение `#f0b429`, верификация `#58a6ff`
- Семь схем оформления через `:root[data-appearance=…]`: Классика,
  Полночь, Графит, День, Сепия и платные Туманность и Золото. Схема
  переопределяет только токены, экраны не правятся; выбор хранится и на
  сервере (`profile.app_theme`), чтобы переезжал между устройствами
- Темы переписки — по паре, а не по устройству: пресеты и произвольные
  цвета (Plus), узоры фона рисуются CSS-градиентами без картинок
- Фон живой: два очень слабых пятна под контентом отвечают акценту
  текущей схемы, закреплены за вьюпортом, анимация 40 с и глохнет по
  `prefers-reduced-motion`. Базовая заливка живёт на `html`, а не на
  `body` — иначе непрозрачный фон `body` закрывает свой же `::before`
- Шрифт Inter, заголовки с `letter-spacing: -0.03em`
- Скругления умеренные: карточки 18px, плитки 12px, контролы 10px
- Стеклянные поверхности: `blur(20px) saturate(160%)` поверх
  `rgb(255 255 255 / 0.05)`
- Тени только нейтральные: цветной ореол — признак «розового»
  интерфейса даже после смены самого цвета
- Движение: пружина `stiffness 380 / damping 34`, уважается
  `prefers-reduced-motion`
- Знак марки — сердце: одно и то же параметрическое сердце на иконке
  приложения (`tools/make_icons.py`), сплэше и баннерах бота
  (`tools/make_banners.py`). Иконки, сплэш и og-превью генерируются из
  тех же токенов палитры

Превью ссылки (`og-image.png`) растрируется из `landing/og-image.svg`
через `rsvg-convert` в `tools/make_icons.py` — раньше генератор молча
затирал его сплэшем, и ссылка на сервис знакомств выглядела заглушкой.

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
