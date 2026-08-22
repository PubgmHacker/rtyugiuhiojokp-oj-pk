"""Ключ рейт-лимита: подделанный Authorization не должен сдвигать счётчик.

Уязвимость, которую здесь прибиваем: ключом лимита служил хвост заголовка
Authorization БЕЗ проверки подписи. На неавторизованных путях
(`/api/auth/link` — обмен шестизначного кода привязки на JWT) атакующий менял
выдуманный «токен» на каждый запрос — счётчик каждый раз начинался с нуля, и
код перебирался без ограничений. Лимит попыток внутри самих кодов
(`services/link_codes.py::MAX_ATTEMPTS`) не спасает: он считается НА КАЖДЫЙ
код отдельно, а перебирающий меняет код на каждой попытке.

Вторая лазейка того же корня: валидный, но каждый раз СВЕЖИЙ JWT (iat/jti
меняются — меняется и хвост подписи) обнулял счётчик жалоб и загрузок для
вполне авторизованного спамера.

Теперь ключ — user_id из проверенного токена, иначе IP. Оба обхода умирают:
мусорный токен считается по IP, а у свежих токенов одного человека один
user_id.
"""

from __future__ import annotations

from fastapi import Request
from jose import jwt

from middleware.auth import create_access_token
from middleware.rate_limit import _client_key


def _запрос(headers: dict[str, str] | None = None, ip: str = "203.0.113.7") -> Request:
    """HTTP-запрос с нужными заголовками — ровно то, что видит middleware."""
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/auth/link",
        "headers": [
            (k.lower().encode(), v.encode()) for k, v in (headers or {}).items()
        ],
        "client": (ip, 4242),
        "query_string": b"",
    })


def test_подделанный_токен_не_сдвигает_ключ():
    """Смена выдуманного токена на каждый запрос не обнуляет счётчик."""
    k1 = _client_key(_запрос({"Authorization": "Bearer AAAA.BBBB.C1"}))
    k2 = _client_key(_запрос({"Authorization": "Bearer AAAA.BBBB.C2"}))
    assert k1 == k2 == "ip:203.0.113.7"


def test_токен_с_чужой_подписью_считается_по_ip():
    """Правдоподобный JWT, подписанный не нашим секретом, — тот же аноним."""
    чужой = jwt.encode({"sub": "victim"}, "not_our_secret_at_all", algorithm="HS256")
    assert _client_key(_запрос({"Authorization": f"Bearer {чужой}"})) == "ip:203.0.113.7"


def test_свежие_токены_одного_человека_дают_один_ключ():
    """Перевыпуск JWT (новые iat/jti) не даёт спамеру новый счётчик."""
    t1 = create_access_token("user-1")
    t2 = create_access_token("user-1")
    assert t1 != t2, "токены обязаны отличаться (jti), иначе тест ничего не ловит"
    k1 = _client_key(_запрос({"Authorization": f"Bearer {t1}"}))
    k2 = _client_key(_запрос({"Authorization": f"Bearer {t2}"}))
    assert k1 == k2 == "u:user-1"


def test_разные_люди_не_делят_счётчик():
    k1 = _client_key(_запрос({"Authorization": f"Bearer {create_access_token('user-1')}"}))
    k2 = _client_key(_запрос({"Authorization": f"Bearer {create_access_token('user-2')}"}))
    assert k1 != k2


def test_без_токена_ключ_по_ip():
    assert _client_key(_запрос()) == "ip:203.0.113.7"
    assert _client_key(_запрос(ip="198.51.100.1")) == "ip:198.51.100.1"
