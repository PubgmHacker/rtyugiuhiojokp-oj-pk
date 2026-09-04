from __future__ import annotations

import json


#: Роли, которым мини-апп рисует золотой бейдж команды. Наружу отдаём
#: только флаг is_official, а не саму роль: постороннему незачем знать,
#: админ перед ним или владелец — это внутренняя иерархия.
РОЛИ_КОМАНДЫ = ("admin", "owner")


def официальный(role) -> bool:
    """Аккаунт команды? Единственное место, где роль превращается в бейдж."""
    return str(role or "") in РОЛИ_КОМАНДЫ


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


def _открывается_чужим_клиентом(значение) -> bool:
    """Ссылка, которую чужой клиент действительно сможет загрузить.

    Бот, если R2 не настроен, хранит в колонке Telegram file_id — чужой
    клиент проиграть его не может, да и раскрывать внутренний
    идентификатор незачем. Отсюда белый список: абсолютный http(s)-адрес
    или путь от корня сайта («/demo-photos/p00-1.jpg») — так лежит то,
    что раздаёт сам фронтенд. Протокольно-относительный «//хост/x.jpg»
    отсекаем: он ведёт на посторонний домен, а не в нашу раздачу.
    file_id со слэша не начинается никогда.
    """
    if not isinstance(значение, str):
        return False
    if значение.startswith(("http://", "https://")):
        return True
    return значение.startswith("/") and not значение.startswith("//")


def public_videos(value) -> list[str]:
    """Видео анкеты, какими их можно показать чужому клиенту.

    Владельцу (/profiles/me, экспорт) список отдаётся как есть — иначе
    PATCH с веба молча стирал бы залитое через бота.
    """
    return [v for v in as_list(value) if _открывается_чужим_клиентом(v)]


def public_photos(value) -> list[str]:
    """Фото, безопасные для выдачи в чужую анкету."""
    return [photo for photo in as_list(value) if _открывается_чужим_клиентом(photo)]
