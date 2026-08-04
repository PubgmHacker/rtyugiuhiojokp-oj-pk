from __future__ import annotations

import base64
import json
import logging
from typing import Optional

from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Lazy import zhipuai — may not be installed in dev
_zhipu_client = None


def _get_zhipu_client():
    global _zhipu_client
    if _zhipu_client is None and settings.ZHIPU_API_KEY:
        try:
            from zhipuai import ZhipuAI
            _zhipu_client = ZhipuAI(api_key=settings.ZHIPU_API_KEY)
        except ImportError:
            logger.warning("zhipuai package not installed")
    return _zhipu_client


async def moderate_text(text: str) -> dict:
    """Проверить текст через GLM-5.2 на нарушение правил.

    Returns: {"safe": bool, "blocked": bool, "reason": str}
    """
    if not text or not text.strip():
        return {"safe": True, "blocked": False, "reason": ""}

    client = _get_zhipu_client()
    if not client:
        # Fallback: simple keyword filter
        return _keyword_filter(text)

    try:
        response = client.chat.completions.create(
            model="glm-4-flash",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a content moderation AI for a dating app. "
                        "Analyze the following text and respond with JSON only:\n"
                        '{"safe": true/false, "blocked": true/false, "reason": "brief explanation"}\n'
                        "Block: NSFW, harassment, hate speech, spam, scam, drugs, violence.\n"
                        "Allow: normal dating bios, compliments, greetings."
                    ),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=200,
        )
        content = response.choices[0].message.content.strip()
        # Try to parse JSON from response
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Extract JSON from possible markdown
            if "{" in content and "}" in content:
                start = content.index("{")
                end = content.rindex("}") + 1
                return json.loads(content[start:end])
            return {"safe": True, "blocked": False, "reason": "Parse error"}
    except Exception as e:
        logger.error(f"AI moderation error: {e}")
        return {"safe": True, "blocked": False, "reason": "AI unavailable"}


async def moderate_image(image_bytes: bytes) -> dict:
    """Проверить фото через GLM-5.2 multimodal.

    Returns: {"safe": bool, "blocked": bool, "reason": str}
    """
    client = _get_zhipu_client()
    if not client:
        return {"safe": True, "blocked": False, "reason": "AI not configured"}

    try:
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        response = client.chat.completions.create(
            model="glm-4v-flash",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a content moderation AI for a dating app. "
                        "Analyze the image. Respond with JSON only:\n"
                        '{"safe": true/false, "blocked": true/false, "reason": "brief explanation"}\n'
                        "Block: nudity, sexual content, violence, weapons, drugs.\n"
                        "Allow: selfies, portraits, lifestyle photos, pets, travel."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": "Analyze this image for dating app content policy."},
                    ],
                },
            ],
            temperature=0.1,
            max_tokens=200,
        )
        content = response.choices[0].message.content.strip()
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            if "{" in content and "}" in content:
                start = content.index("{")
                end = content.rindex("}") + 1
                return json.loads(content[start:end])
            return {"safe": True, "blocked": False, "reason": "Parse error"}
    except Exception as e:
        logger.error(f"AI image moderation error: {e}")
        return {"safe": True, "blocked": False, "reason": "AI unavailable"}


def _keyword_filter(text: str) -> dict:
    """Simple fallback keyword filter when AI is unavailable."""
    blocked_words = [
        "escort", "проститут", "секс за деньги", " наркотик", "наркотик",
        "оружие", "убить", "самоубийств",
    ]
    text_lower = text.lower()
    for word in blocked_words:
        if word in text_lower:
            return {"safe": False, "blocked": True, "reason": f"Prohibited content: {word}"}
    return {"safe": True, "blocked": False, "reason": ""}


async def log_moderation(
    user_id: str,
    content_type: str,
    content: str,
    verdict: dict,
) -> None:
    """Записать вердикт модерации в журнал для админки.

    Журнал — единственный способ разобрать спорную блокировку постфактум,
    поэтому пишем и безопасные проверки тоже.

    Пишем в СВОЕЙ сессии, а не в сессии запроса: при блокировке роутер бросает
    HTTPException, зависимость делает rollback — и запись о самом интересном
    случае исчезла бы вместе с ним. Сбой записи журнала не должен ломать
    сценарий: пользователь не виноват, что журнал недоступен.
    """
    from database.connection import async_session_factory
    from models.models import AiModerationLog

    result = "blocked" if verdict.get("blocked") else ("safe" if verdict.get("safe", True) else "warning")
    try:
        async with async_session_factory() as session:
            session.add(
                AiModerationLog(
                    user_id=user_id,
                    content_type=content_type,
                    # Длинные тексты режем: журналу нужен повод, а не весь контент
                    content=(content or "")[:2000],
                    result=result,
                    action="none",
                    reason=verdict.get("reason", "") or "",
                )
            )
            await session.commit()
    except Exception as e:
        logger.error(f"Не удалось записать лог модерации: {e}")
