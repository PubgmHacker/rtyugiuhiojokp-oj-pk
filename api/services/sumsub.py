"""Клиент Sumsub — проверка «живости» силами KYC-провайдера.

Зачем при живой встроенной проверке ещё и провайдер: у Sumsub специализированная
модель Liveness (3D-съёмка, анти-дипфейк, сертификация iBeta PAD), и провайдерская
галочка вызывает больше доверия, чем самописная. Встроенная схема остаётся
запасной: без ключей (`sumsub_enabled == False`) роутер работает как раньше.

Из всего KYC-набора Sumsub используется ОДИН шаг — Selfie (Liveness): человек
крутит головой перед камерой, и всё. Документы (паспорт, ID) не запрашиваются
никогда: уровень в дашборде собирается без шага Identity document, и код ниже
не читает из заявки ничего, кроме кадра селфи. Галочке знакомств нужна
живость и совпадение лица с анкетой, а не имя по паспорту.

Роли по данным: кадры в провайдерском режиме снимает и обрабатывает Sumsub
как процессор — на наш сервер биометрия не приходит вообще, кроме одного
момента: после GREEN мы скачиваем ОДИН кадр селфи, в памяти сверяем лицо с
фото анкеты (галочка обязана значить «в анкете — он же») и тут же забываем.
Ни в R2, ни в БД, ни в журнал кадр не попадает — как и во встроенной схеме.

API подписывается по схеме Sumsub App Token:
`X-App-Access-Sig = HMAC-SHA256(secret, ts + METHOD + path_с_query + body)`,
hex в нижнем регистре; `ts` — unix-секунды, допуск ±1 минута от их сервера.

Fail-closed повсюду: не ответил Sumsub — `SumsubUnavailable`, роутер отдаёт
503, попытка не сжигается. Никаких «пропустим без проверки».
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from urllib.parse import quote

import httpx

from config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

#: Сетевые вызовы к Sumsub. Дольше 15 секунд ждать нечего: клиент в мини-аппе
#: держит открытый лоадер, а вебхук Sumsub сам повторит доставку.
_ТАЙМАУТ = 15.0

#: Сколько живёт токен WebSDK. Сам SDK по истечении дёргает наш колбэк за
#: новым, так что короткий срок безопасен и рекомендован документацией.
TOKEN_TTL_SECS = 600

#: Алгоритмы подписи вебхука из Webhook manager. Ключ — значение заголовка
#: `X-Payload-Digest-Alg`; по умолчанию Sumsub шлёт HMAC_SHA256_HEX.
_АЛГОРИТМЫ_ВЕБХУКА = {
    "HMAC_SHA1_HEX": hashlib.sha1,
    "HMAC_SHA256_HEX": hashlib.sha256,
    "HMAC_SHA512_HEX": hashlib.sha512,
}

#: Типы документов Sumsub, за которыми стоит кадр лица с шага Liveness.
_ТИПЫ_СЕЛФИ = ("SELFIE", "VIDEO_SELFIE")


class SumsubUnavailable(Exception):
    """Sumsub не ответил или ответил ерундой — проверка не состоялась."""


def _sign(secret: str, ts: int, method: str, path: str, body: bytes) -> str:
    """Подпись запроса: HMAC-SHA256 от `ts + METHOD + path + body`.

    `path` — с query-строкой, ровно как уйдёт в запрос: подпись считается
    по тем же байтам, что видит сервер, иначе 401.
    """
    сообщение = f"{ts}{method.upper()}{path}".encode() + body
    return hmac.new(secret.encode(), сообщение, hashlib.sha256).hexdigest()


def _headers(method: str, path: str, body: bytes) -> dict[str, str]:
    ts = int(time.time())
    return {
        "X-App-Token": settings.SUMSUB_APP_TOKEN,
        "X-App-Access-Ts": str(ts),
        "X-App-Access-Sig": _sign(settings.SUMSUB_SECRET_KEY, ts, method, path, body),
        "Accept": "application/json",
    }


async def _request(method: str, path: str, json_body: dict | None = None) -> httpx.Response:
    """Подписанный запрос к Sumsub. Сетевые сбои переводятся в SumsubUnavailable."""
    body = b""
    заголовки_дополнительно: dict[str, str] = {}
    if json_body is not None:
        # Подписываются РОВНО отправляемые байты — сериализуем один раз сами
        body = json.dumps(json_body, separators=(",", ":")).encode()
        заголовки_дополнительно["Content-Type"] = "application/json"
    try:
        async with httpx.AsyncClient(
            base_url=settings.SUMSUB_BASE_URL, timeout=_ТАЙМАУТ
        ) as client:
            return await client.request(
                method,
                path,
                content=body or None,
                headers={**_headers(method, path, body), **заголовки_дополнительно},
            )
    except httpx.HTTPError as exc:
        logger.error(f"Sumsub недоступен: {method} {path}: {exc}")
        from services.alerting import capture_exception

        capture_exception(exc)
        raise SumsubUnavailable(str(exc)) from exc


async def create_access_token(user_id: str) -> dict:
    """Токен для WebSDK: {"token": ..., "expires_in": TOKEN_TTL_SECS}.

    `user_id` становится externalUserId заявителя — по нему вебхук и опрос
    находят нашего человека. Уровень (какие шаги проходить) задаёт
    SUMSUB_LEVEL_NAME и он чувствителен к регистру.
    """
    ответ = await _request(
        "POST",
        "/resources/accessTokens/sdk",
        {
            "userId": user_id,
            "levelName": settings.SUMSUB_LEVEL_NAME,
            "ttlInSecs": TOKEN_TTL_SECS,
        },
    )
    if ответ.status_code != 200:
        logger.error(
            f"Sumsub не выдал токен: HTTP {ответ.status_code} {ответ.text[:300]}"
        )
        raise SumsubUnavailable(f"accessTokens/sdk HTTP {ответ.status_code}")
    данные = ответ.json()
    токен = данные.get("token")
    if not токен:
        raise SumsubUnavailable("accessTokens/sdk: ответ без token")
    return {"token": токен, "expires_in": TOKEN_TTL_SECS}


async def applicant_status(user_id: str) -> dict | None:
    """Заявитель по externalUserId: {"applicant_id", "review_answer", "reject_type",
    "moderation_comment"} либо None, если заявителя ещё нет.

    `review_answer` пуст, пока проверка не завершена (человек ещё снимает
    или Sumsub ещё думает).
    """
    путь = f"/resources/applicants/-;externalUserId={quote(user_id, safe='')}/one"
    ответ = await _request("GET", путь)
    if ответ.status_code == 404:
        return None
    if ответ.status_code != 200:
        logger.error(
            f"Sumsub не отдал заявителя: HTTP {ответ.status_code} {ответ.text[:300]}"
        )
        raise SumsubUnavailable(f"applicants/one HTTP {ответ.status_code}")
    данные = ответ.json()
    review = данные.get("review") or {}
    result = review.get("reviewResult") or {}
    return {
        "applicant_id": данные.get("id") or "",
        "review_answer": result.get("reviewAnswer") or "",
        "reject_type": result.get("reviewRejectType") or "",
        "moderation_comment": result.get("moderationComment") or "",
    }


async def best_selfie_frame(applicant_id: str) -> bytes | None:
    """Свежий кадр селфи заявителя — для сверки лица с фото анкеты.

    Кадр живёт только в памяти вызвавшего: сюда он приходит байтами и байтами
    уходит, никакого сохранения. None — селфи в заявке не нашлось (уровень
    без шага Liveness или заявка пуста): решать по такой заявке нечего.
    """
    ответ = await _request(
        "GET", f"/resources/applicants/{quote(applicant_id, safe='')}/metadata/resources"
    )
    if ответ.status_code != 200:
        logger.error(
            f"Sumsub не отдал список кадров: HTTP {ответ.status_code} {ответ.text[:300]}"
        )
        raise SumsubUnavailable(f"metadata/resources HTTP {ответ.status_code}")
    элементы = (ответ.json() or {}).get("items") or []
    селфи = [
        э
        for э in элементы
        if not э.get("deactivated")
        and ((э.get("idDocDef") or {}).get("idDocType") in _ТИПЫ_СЕЛФИ)
    ]
    if not селфи:
        return None
    # Свежайший кадр: при повторной сдаче в заявке копятся старые, а GREEN
    # относится к последней. addedDate у Sumsub сортируется лексикографически.
    селфи.sort(key=lambda э: str(э.get("addedDate") or ""))
    ид_кадра = селфи[-1].get("id")
    if not ид_кадра:
        return None
    кадр = await _request(
        "GET",
        f"/resources/applicants/{quote(applicant_id, safe='')}/resources/"
        f"{quote(str(ид_кадра), safe='')}",
    )
    if кадр.status_code != 200:
        logger.error(f"Sumsub не отдал кадр селфи: HTTP {кадр.status_code}")
        raise SumsubUnavailable(f"resources/{ид_кадра} HTTP {кадр.status_code}")
    return кадр.content


def verify_webhook_digest(raw_body: bytes, digest: str, alg: str) -> bool:
    """Подпись вебхука: HMAC от СЫРЫХ байтов тела ключом из Webhook manager.

    Сравнение только через compare_digest — обычное `==` утекает временем.
    Неизвестный алгоритм и пустой секрет — отказ, а не «ну ладно».
    """
    секрет = settings.SUMSUB_WEBHOOK_SECRET
    if not секрет or not digest:
        return False
    хеш = _АЛГОРИТМЫ_ВЕБХУКА.get((alg or "HMAC_SHA256_HEX").upper())
    if хеш is None:
        return False
    ожидаемая = hmac.new(секрет.encode(), raw_body, хеш).hexdigest()
    return hmac.compare_digest(ожидаемая, digest.strip().lower())
