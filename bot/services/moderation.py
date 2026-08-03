"""Модерация контента для бота.

Регистрация через бота — основной канал, и раньше он полностью обходил
проверку контента: фото и текст попадали в анкету напрямую. Здесь та же
логика, что в `api/services/ai_moderation.py`, чтобы правила совпадали
в обоих каналах.

Ключевой принцип: сбой AI-сервиса не должен блокировать регистрацию,
поэтому при ошибке остаётся словарный фильтр, а не полный отказ.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

from config import ZHIPU_API_KEY

logger = logging.getLogger(__name__)

_client = None
_client_tried = False

# Внешний вызов не должен подвешивать регистрацию
_AI_TIMEOUT = 12.0

SAFE: dict = {"safe": True, "blocked": False, "reason": ""}

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

_BLOCKED_WORDS = (
    "escort",
    "проститут",
    "секс за деньги",
    "интим услуг",
    "наркотик",
    "закладк",
    "оружие",
    "убить",
    "самоубийств",
    "продам аккаунт",
    "инвестиц",
    "заработок от",
)


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

        _client = ZhipuAI(api_key=ZHIPU_API_KEY)
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
    for word in _BLOCKED_WORDS:
        if word in low:
            return {"safe": False, "blocked": True, "reason": "spam"}
    return dict(SAFE)


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
        "reason": str(data.get("reason", ""))[:200],
    }


async def moderate_text(text: str) -> dict:
    """Проверка текста анкеты. Возвращает {safe, blocked, reason}."""
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
            model="glm-4-flash",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You moderate profile text for a dating app. "
                        "Answer with JSON only: "
                        '{"safe": bool, "blocked": bool, "reason": "short code"}. '
                        "Block sexual services, escort ads, drugs, weapons, scams, "
                        "spam, contact details, and any hint the author is a minor. "
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
        return _parse_verdict(raw)
    except asyncio.TimeoutError:
        logger.warning("Модерация текста: таймаут, применён словарный фильтр")
        return keyword
    except Exception as e:
        logger.warning(f"Модерация текста недоступна: {e}")
        return keyword


async def moderate_image(image_bytes: bytes) -> dict:
    """Проверка фотографии. При недоступности AI фото пропускается."""
    if not image_bytes:
        return dict(SAFE)

    client = _get_client()
    if not client:
        return dict(SAFE)

    encoded = base64.b64encode(image_bytes).decode()

    def _call():
        response = client.chat.completions.create(
            model="glm-4v-flash",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Moderate this dating profile photo. Answer with JSON "
                                'only: {"safe": bool, "blocked": bool, "reason": "short code"}. '
                                "Block nudity, sexual content, violence, weapons, drugs, "
                                "and photos that appear to show a minor."
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
        return _parse_verdict(raw)
    except asyncio.TimeoutError:
        logger.warning("Модерация фото: таймаут, фото пропущено")
        return dict(SAFE)
    except Exception as e:
        logger.warning(f"Модерация фото недоступна: {e}")
        return dict(SAFE)
