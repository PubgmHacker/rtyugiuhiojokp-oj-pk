"""Модерация контента для бота.

Регистрация через бота — основной канал, и раньше он полностью обходил
проверку контента: фото и текст попадали в анкету напрямую. Здесь та же
логика, что в `api/services/ai_moderation.py`, чтобы правила совпадали
в обоих каналах.

Деградация у текста и фото разная — намеренно:

* Текст при сбое AI проверяется словарным фильтром: это осмысленная
  замена, очевидные нарушения он ловит.
* Фото заменить нечем. Пропускать его «пока модерация лежит» — значит
  впускать в общую выдачу что угодно ровно тогда, когда фильтра нет;
  на этом канале живут и снимки несовершеннолетних, и порнография.
  Поэтому в проде фото без проверки отклоняется (fail-closed) с честным
  «попробуйте позже», а в DEBUG пропускается — локальный стенд обязан
  работать без внешних ключей.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

from config import (
    DEBUG,
    ZHIPU_API_KEY,
    ZHIPU_BASE_URL,
    ZHIPU_TEXT_MODEL,
    ZHIPU_VISION_MODEL,
)

logger = logging.getLogger(__name__)

_client = None
_client_tried = False

# Внешний вызов не должен подвешивать регистрацию
_AI_TIMEOUT = 12.0

SAFE: dict = {"safe": True, "blocked": False, "category": "", "reason": ""}

#: Категории blocked-текстов — закрытое множество, то же, что TEXT_CATEGORIES
#: в api/services/ai_moderation.py: по категории enforcement считает страйки
#: и выбирает лестницу бана, поэтому выдуманная моделью категория сюда не
#: проходит (мета-тест в api/tests сверяет оба кортежа).
TEXT_CATEGORIES = ("ad", "heavy", "text")

#: Вердикт «проверка не состоялась»: фото не плохое — его просто не посмотрели.
#: `unavailable` даёт обработчику показать «попробуйте позже» вместо
#: обвинения снимка; `blocked=True` — чтобы забытая проверка ключа
#: где-нибудь в новом коде по умолчанию НЕ пропустила фото.
UNAVAILABLE: dict = {
    "safe": False,
    "blocked": True,
    "unavailable": True,
    "reason": "модерация недоступна",
}

# Понятные пользователю формулировки вместо технических кодов
_REASON_RU = {
    "nudity": "нагота или откровенное содержание",
    "nsfw": "откровенное содержание",
    "sexual": "содержание сексуального характера",
    "violence": "насилие",
    "weapon": "оружие",
    "drugs": "наркотические вещества",
    "spam": "спам или реклама",
    "scam": "признаки мошенничества",
    "contact": "контактные данные в тексте",
    "minor": "признаки несовершеннолетия",
    "no_face": "на фото не видно человека",
}

# Словарь по категориям: (маркер, код причины для humanize). Категории — те
# же, что у API, чтобы одинаковый текст копил один и тот же счёт страйков.
# Маркеры ссылок/юзернеймов взяты из апишного _KEYWORD_CATEGORIES: в боте
# словарь стоит ДО обращения к AI и раньше рекламу вовсе не ловил; остальной
# набор шире апишного — это осознанно, бот исторически фильтровал жёстче.
_KEYWORD_CATEGORIES: dict[str, tuple[tuple[str, str], ...]] = {
    "heavy": (
        ("escort", "sexual"),
        ("проститут", "sexual"),
        ("секс за деньги", "sexual"),
        ("интим услуг", "sexual"),
        ("наркотик", "drugs"),
        ("закладк", "drugs"),
        ("оружие", "weapon"),
        ("убить", "violence"),
    ),
    # «самоубийств» — text, не heavy: кризисный контент требует мягкости,
    # а не самой жёсткой лестницы (то же решение, что в API)
    "text": (("самоубийств", "selfharm"),),
    "ad": (
        ("t.me/", "spam"),
        ("telegram.me/", "spam"),
        ("http://", "spam"),
        ("https://", "spam"),
        ("www.", "spam"),
        ("wa.me/", "spam"),
        ("промокод", "spam"),
        ("подпишись на", "spam"),
        ("продам аккаунт", "scam"),
        ("инвестиц", "scam"),
        ("заработок от", "scam"),
    ),
}


def _get_client():
    """Клиент Zhipu создаётся один раз и только при наличии ключа."""
    global _client, _client_tried
    if _client_tried:
        return _client
    _client_tried = True
    if not ZHIPU_API_KEY:
        logger.info("ZHIPU_API_KEY не задан — модерация работает по словарю")
        return None
    try:
        from zhipuai import ZhipuAI

        # Конечный таймаут обязателен: вызов синхронный, и зависший Zhipu
        # держал бы поток executor бесконечно (см. api/services/ai_moderation)
        kwargs = {"api_key": ZHIPU_API_KEY, "timeout": 15.0}
        # base_url только когда задан: пустая строка сломала бы URL,
        # а отсутствие аргумента оставляет SDK его дефолт (материк)
        if ZHIPU_BASE_URL:
            kwargs["base_url"] = ZHIPU_BASE_URL
        _client = ZhipuAI(**kwargs)
    except ImportError:
        logger.warning("Пакет zhipuai не установлен — модерация по словарю")
    except Exception as e:
        logger.warning(f"Не удалось создать клиент Zhipu: {e}")
    return _client


def humanize(reason: str) -> str:
    """Технический код причины → формулировка для пользователя."""
    if not reason:
        return "не проходит проверку"
    low = reason.lower()
    for key, ru in _REASON_RU.items():
        if key in low:
            return ru
    # Если модель ответила по-английски, не показываем это пользователю
    if all(ord(c) < 128 for c in reason):
        return "не проходит проверку"
    return reason[:120]


def _keyword_filter(text: str) -> dict:
    low = (text or "").lower()
    for category, слова in _KEYWORD_CATEGORIES.items():
        for word, код in слова:
            if word in low:
                return {
                    "safe": False,
                    "blocked": True,
                    "category": category,
                    "reason": код,
                }
    return dict(SAFE)


def _normalize_text_verdict(raw: dict) -> dict:
    """Привести вердикт текста к контракту {safe, blocked, category, reason}.

    Копия апишного _normalize_text_verdict: модель может вернуть что угодно —
    без category, с выдуманной категорией, с blocked-строкой вместо bool.
    Хендлеры ветвятся по blocked, а enforcement выбирает правило по category,
    поэтому оба поля обязаны быть предсказуемыми. Blocked без валидной
    категории падает в "text" — самое мягкое правило.
    """
    blocked = bool(raw.get("blocked"))
    category = raw.get("category") if blocked else ""
    if blocked and category not in TEXT_CATEGORIES:
        category = "text"
    return {
        "safe": not blocked,
        "blocked": blocked,
        "category": category or "",
        "reason": raw.get("reason", "") or "",
    }


def _normalize_image_verdict(raw: dict) -> dict:
    """Привести вердикт фото к контракту {safe, blocked, category, reason}.

    Копия апишного _normalize_image_verdict: у фото category бывает только
    "ad" (реклама В КАДРЕ: юзернеймы, ссылки, QR, промо) или "" — за "ad"
    хендлер вешает тот же страйк, что за рекламный текст. Прочие блокировки
    (нудити, оружие) остаются с пустой категорией: отказ без страйка.
    Нормализация в "text", как у текста, запрещена — фото-модель ошибается
    чаще, и каждый её блок превращался бы в шаг к бану.
    """
    blocked = bool(raw.get("blocked"))
    category = raw.get("category") if blocked else ""
    return {
        "safe": not blocked,
        "blocked": blocked,
        "category": "ad" if category == "ad" else "",
        "reason": raw.get("reason", "") or "",
    }


def _parse_verdict(raw: str) -> dict:
    """Достаёт JSON-вердикт из ответа модели, терпимо к обёрткам."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return dict(SAFE)
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return dict(SAFE)
    return {
        "safe": bool(data.get("safe", True)),
        "blocked": bool(data.get("blocked", False)),
        # Сырая категория: текстовый вердикт дальше прогоняется через
        # _normalize_text_verdict, фото — через _normalize_image_verdict
        "category": str(data.get("category", "") or ""),
        "reason": str(data.get("reason", ""))[:200],
    }


async def moderate_text(text: str) -> dict:
    """Проверка текста анкеты. Возвращает {safe, blocked, category, reason}.

    category — из TEXT_CATEGORIES при blocked, "" при safe. По ней
    services/enforcement.py решает, когда предупреждать, а когда банить.
    """
    if not text or not text.strip():
        return dict(SAFE)

    # Словарь отсекает очевидное до обращения к сети
    keyword = _keyword_filter(text)
    if keyword["blocked"]:
        return keyword

    client = _get_client()
    if not client:
        return keyword

    def _call():
        response = client.chat.completions.create(
            model=ZHIPU_TEXT_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        # Категории — те же, что в апишном промпте: одинаковый
                        # текст обязан получать одинаковую категорию в обоих
                        # каналах, счёт страйков общий
                        "You moderate profile text for a dating app. "
                        "Answer with JSON only: "
                        '{"safe": bool, "blocked": bool, '
                        '"category": "ad"/"heavy"/"text"/"", "reason": "short code"}. '
                        "When blocked, set category:\n"
                        '- "ad": advertising or audience funneling — external links, '
                        "usernames/handles (@name, t.me/..., wa.me/...), channel or "
                        "group invites, selling goods/services, promo codes, "
                        "job/recruiting spam.\n"
                        '- "heavy": drugs, paid sexual services or escort, fraud/scam '
                        "schemes, threats of violence, anything sexualizing minors.\n"
                        '- "text": harassment, insults, hate speech, explicit sexual '
                        "text, other rule violations.\n"
                        'When safe, category is "". '
                        "Ordinary self-description is safe."
                    ),
                },
                {"role": "user", "content": text[:1500]},
            ],
            temperature=0.1,
        )
        return response.choices[0].message.content

    try:
        raw = await asyncio.wait_for(asyncio.to_thread(_call), timeout=_AI_TIMEOUT)
        return _normalize_text_verdict(_parse_verdict(raw))
    except asyncio.TimeoutError:
        logger.warning("Модерация текста: таймаут, применён словарный фильтр")
        return keyword
    except Exception as e:
        logger.warning(f"Модерация текста недоступна: {e}")
        return keyword


async def moderate_image(image_bytes: bytes) -> dict:
    """Проверка фотографии. Возвращает {safe, blocked, category, reason}.

    category == "ad" — на снимке реклама (наложенные юзернеймы, ссылки, QR,
    промо): хендлер вешает за это тот же страйк, что за рекламный текст.
    Прочие блокировки идут с пустой категорией — отказ без страйка.

    Прод без работающего AI фото НЕ пропускает (см. докстринг модуля):
    возвращается ``UNAVAILABLE``, и обработчик просит попробовать позже.
    В DEBUG — пропускает, чтобы стенд жил без ключей.
    """
    if not image_bytes:
        # Пустые байты — ошибка вызывающего кода, а не «безопасное фото»
        return dict(UNAVAILABLE) if not DEBUG else dict(SAFE)

    client = _get_client()
    if not client:
        if DEBUG:
            return dict(SAFE)
        logger.error(
            "Модерация фото не настроена (ZHIPU_API_KEY/zhipuai) — "
            "фото отклонено (fail-closed)"
        )
        return dict(UNAVAILABLE)

    encoded = base64.b64encode(image_bytes).decode()

    def _call():
        response = client.chat.completions.create(
            model=ZHIPU_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                # Правило "ad" — то же, что в апишном промпте
                                # (api/services/ai_moderation.py): реклама на
                                # фото копит общий счёт страйков "ad"
                                "Moderate this dating profile photo. Answer with JSON "
                                'only: {"safe": bool, "blocked": bool, '
                                '"category": "ad"/"", "reason": "short code"}. '
                                "Block nudity, sexual content, violence, weapons, drugs, "
                                "and photos that appear to show a minor. "
                                'Also block with category "ad": advertising in the '
                                "image — overlaid or clearly readable usernames/handles "
                                "(@name, t.me/..., wa.me/...), links, QR codes, phone "
                                "numbers, promo of channels/services, watermarks of "
                                "other apps, price lists or sales pitches. "
                                'For any other block, category is "". '
                                "Incidental background text (street signs, book covers, "
                                "clothing brands) is NOT advertising."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": encoded}},
                    ],
                }
            ],
            temperature=0.1,
        )
        return response.choices[0].message.content

    try:
        raw = await asyncio.wait_for(asyncio.to_thread(_call), timeout=_AI_TIMEOUT)
        return _normalize_image_verdict(_parse_verdict(raw))
    except asyncio.TimeoutError:
        if DEBUG:
            logger.warning("Модерация фото: таймаут, фото пропущено (DEBUG)")
            return dict(SAFE)
        logger.error("Модерация фото: таймаут — фото отклонено (fail-closed)")
        return dict(UNAVAILABLE)
    except Exception as e:
        if DEBUG:
            logger.warning(f"Модерация фото недоступна: {e} — пропущено (DEBUG)")
            return dict(SAFE)
        logger.error(f"Модерация фото недоступна: {e} — фото отклонено (fail-closed)")
        return dict(UNAVAILABLE)


#: Вердикт «гейт фото анкеты не состоялся» — та же семантика, что UNAVAILABLE:
#: фото не плохое, его просто не посмотрели; без вердикта в анкету не пускаем.
GATE_UNAVAILABLE: dict = {
    "face": False,
    "authentic": False,
    "unavailable": True,
    "reason": "проверка недоступна",
}

#: Гейт пройден (DEBUG или заглушки) — на бою так отвечает только модель.
_GATE_PASS: dict = {"face": True, "authentic": True, "reason": ""}


async def verify_profile_photo(image_bytes: bytes) -> dict:
    """Жёсткий гейт фото анкеты: на снимке — реальный человек, а не подмена.

    Та же проверка, что в `api/services/ai_moderation.py`: `moderate_image`
    выше отвечает «нет ли запрещённого», а этот гейт — «есть ли здесь живой
    человек». Кот, чёрный фон, пейзаж или скриншот из интернета модерацию
    проходят как «безопасные», но анкете с ними в общей выдаче делать нечего.

    Возвращает {"face": bool, "authentic": bool, "reason": str}
    (+ "unavailable": True, когда проверка не состоялась):
    * face — на фото есть настоящее человеческое лицо, различимое глазом;
    * authentic — снимок похож на собственную фотографию, а не на скачанную
      картинку (скриншоты, вотермарки, знаменитости, генерация — false).

    Fail-closed в проде, в DEBUG проходит без ключа — как moderate_image.
    """
    if not image_bytes:
        return dict(GATE_UNAVAILABLE) if not DEBUG else dict(_GATE_PASS)

    client = _get_client()
    if not client:
        if DEBUG:
            return dict(_GATE_PASS)
        logger.error(
            "Гейт фото анкеты не настроен (ZHIPU_API_KEY/zhipuai) — "
            "фото отклонено (fail-closed)"
        )
        return dict(GATE_UNAVAILABLE)

    encoded = base64.b64encode(image_bytes).decode()

    def _call():
        response = client.chat.completions.create(
            model=ZHIPU_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "You are a strict profile photo gate for a dating "
                                "app. Every profile photo must show the real person "
                                "who owns the profile. Answer with JSON only: "
                                '{"face": bool, "authentic": bool, "reason": "short code"}. '
                                "face=true ONLY if the image clearly shows a real "
                                "human face recognizable enough to identify the "
                                "person. face=false for animals, objects, landscapes, "
                                "memes, black/solid backgrounds, text images, "
                                "cartoons, body parts without a face, backs of "
                                "heads, silhouettes, or faces too small/dark/blurry. "
                                "authentic=false if the photo looks downloaded or "
                                "fake rather than the user's own: screenshots with "
                                "UI elements or watermarks, photos of screens, stock "
                                "photos, recognizable celebrities, AI-generated "
                                "faces, drawings, or heavily filtered images. "
                                "Ordinary phone selfies and portraits are both true."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": encoded}},
                    ],
                }
            ],
            temperature=0.1,
        )
        return response.choices[0].message.content

    def _разобрать(raw: str) -> dict:
        text = (raw or "").strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return dict(GATE_UNAVAILABLE) if not DEBUG else dict(_GATE_PASS)
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return dict(GATE_UNAVAILABLE) if not DEBUG else dict(_GATE_PASS)
        return {
            "face": bool(data.get("face", False)),
            "authentic": bool(data.get("authentic", False)),
            "reason": str(data.get("reason", ""))[:200],
        }

    try:
        raw = await asyncio.wait_for(asyncio.to_thread(_call), timeout=_AI_TIMEOUT)
        return _разобрать(raw)
    except asyncio.TimeoutError:
        if DEBUG:
            logger.warning("Гейт фото анкеты: таймаут, пропущено (DEBUG)")
            return dict(_GATE_PASS)
        logger.error("Гейт фото анкеты: таймаут — фото отклонено (fail-closed)")
        return dict(GATE_UNAVAILABLE)
    except Exception as e:
        if DEBUG:
            logger.warning(f"Гейт фото анкеты недоступен: {e} — пропущено (DEBUG)")
            return dict(_GATE_PASS)
        logger.error(f"Гейт фото анкеты недоступен: {e} — фото отклонено (fail-closed)")
        return dict(GATE_UNAVAILABLE)
