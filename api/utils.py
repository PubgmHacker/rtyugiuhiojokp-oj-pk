from __future__ import annotations

import json


def as_list(value) -> list:
    """Нормализует JSON-колонку (photos/interests): принимает list или JSON-строку.

    Исторически часть кода писала json.dumps в JSON-колонку — читаем оба формата.
    """
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def public_videos(value) -> list[str]:
    """Видео анкеты, какими их можно показать чужому клиенту.

    Бот, если R2 не настроен, хранит в колонке Telegram file_id — чужой
    клиент проиграть его не может (и это внутренний идентификатор), поэтому
    во все ответы про ЧУЖИЕ анкеты идут только публичные URL. Владельцу
    (/profiles/me, экспорт) список отдаётся как есть — иначе PATCH с веба
    молча стирал бы залитое через бота.
    """
    return [
        v for v in as_list(value) if isinstance(v, str) and v.startswith("http")
    ]
