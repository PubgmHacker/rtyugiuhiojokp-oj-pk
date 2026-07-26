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
