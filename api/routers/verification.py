"""Подтверждение профиля живой съёмкой — галочка «проверенный».

Как в KYC у криптосервисов: сервер выдаёт задание из случайных поз
(анфас + два поворота головы), клиент снимает по кадру на позу с фронтальной
камеры, AI сверяет живость, отсутствие нейросетевой подмены лица (face swap,
дипфейк-фильтры), порядок поз и совпадение лица с фото анкеты.
Прошёл — `is_verified = True`, и бейдж в деке/анкете говорит правду.

Принципы, на которых всё держится:

* **Кадры — биометрия, и она не хранится.** Файлы живут в памяти запроса:
  санитизация → вердикт → забыты. Ни в R2, ни в журнал модерации, ни в
  `dating_verification_attempts` кадры не попадают — только задание и итог.
* **Fail-closed.** Нет вердикта (AI лёг, ключа нет) — нет галочки, 503,
  задание не сжигается. Пропускать проверку при сбое — значит раздавать
  бейдж доверия именно тогда, когда проверить некому.
* **Позы случайны на каждое задание.** Заранее записанное видео не пройдёт:
  порядок поз неизвестен до выдачи задания, а задание живёт СРОК_ЗАДАНИЯ.
* **Лимит отказов суточный и живёт в БД**, а не только в Redis-лимитере:
  перебор фотографий чужого человека не должен переживать сбой кеша.

Режима два, и включается ровно один. Встроенный (по умолчанию): позы + GLM,
всё выше — про него. Провайдерский (`sumsub_enabled`): съёмку, живость и
анти-дипфейк делает Sumsub через свой WebSDK, а сервер после GREEN сверяет
селфи из заявки с фото анкеты и только тогда ставит галочку — провайдер не
знает, чьи фото в анкете. Принципы (кадры не хранятся, fail-closed, суточный
лимит) действуют в обоих режимах; встроенные эндпоинты при включённом
провайдере закрыты, чтобы сильную проверку нельзя было обойти слабой.
"""
from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from database.connection import get_session
from middleware.auth import BANNED_CODE, get_current_user
from models.models import Profile, User, VerificationAttempt
from services import sumsub
from services.ai_moderation import (
    log_moderation,
    verify_face_match,
    verify_liveness,
    verify_person_in_photo,
)
from services.enforcement import register_identity_strike
from services.image_sanitizer import ImageRejected, sanitize_image
from services.notifications import записать_уведомление
from utils import as_list

settings = get_settings()
logger = logging.getLogger(__name__)
router = APIRouter(prefix="/verification", tags=["verification"])

#: Первый кадр всегда анфас — он же база для сравнения с фото анкеты.
#: Остальные позы берутся случайно, чтобы заранее записанное видео не подошло.
ПОЗА_АНФАС = "straight"
ПОЗЫ_ПУЛ = ("left", "right", "up", "smile")
#: Сколько случайных поз добавляется к анфасу. Итого кадров: 1 + это число.
СЛУЧАЙНЫХ_ПОЗ = 2

#: Как позы называются модели. Коды наружу (клиент рисует по ним подсказки),
#: описания — внутрь промпта: «left» модель может понять как угодно,
#: «head turned to the left» — однозначно.
ОПИСАНИЕ_ПОЗ_EN = {
    "straight": "facing straight at the camera",
    "left": "head turned to the left",
    "right": "head turned to the right",
    "up": "head tilted up",
    "smile": "smiling at the camera",
}

#: Сколько живёт выданное задание. Дольше — и позы перестают быть «свежими»:
#: их можно успеть отснять не в кадре, смонтировать, переснять с экрана.
СРОК_ЗАДАНИЯ = timedelta(minutes=10)

#: Сколько отказов за сутки терпим, прежде чем закрыть проверку до завтра.
#: Это защита не от неловкости (свет, ракурс), а от перебора: человек с
#: чужими фото не должен получить сотню попыток подогнать съёмку.
СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ = 5

#: Кадр с фронталки после сжатия в JPEG весит сотни килобайт; 5 МБ — щедрый
#: потолок, всё сверх — не кадр, а попытка накормить сервер мусором.
КАДР_МАКС_БАЙТ = 5 * 1024 * 1024

#: Причины отказа — человеку, на его языке. Технический reason от модели
#: уходит только в журнал модерации.
_ПРИЧИНЫ_РУ = (
    ("live", "Похоже на съёмку экрана или готового фото — нужна живая съёмка лица"),
    ("real_face", "Лицо выглядит изменённым или сгенерированным — снимите без фильтров, масок и обработки"),
    ("poses_match", "Позы не совпали с заданием — повторите их в указанном порядке"),
    ("same_person", "На кадрах будто разные люди — переснимите за один подход"),
    ("matches_profile", "Лицо на кадрах не совпало с фото анкеты"),
)


def _человеческая_причина(вердикт: dict) -> str:
    for ключ, текст in _ПРИЧИНЫ_РУ:
        if not вердикт.get(ключ):
            return текст
    return "Проверка не пройдена — попробуйте ещё раз при хорошем свете"


async def _активное_задание(
    session: AsyncSession, user_id: str
) -> VerificationAttempt | None:
    """Последнее выданное и не истёкшее задание встроенной проверки."""
    граница = datetime.now(timezone.utc) - СРОК_ЗАДАНИЯ
    result = await session.execute(
        select(VerificationAttempt)
        .where(
            VerificationAttempt.user_id == user_id,
            VerificationAttempt.provider == "builtin",
            VerificationAttempt.status == "issued",
            VerificationAttempt.created_at >= граница,
        )
        .order_by(VerificationAttempt.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _выданная_sumsub(
    session: AsyncSession, user_id: str
) -> VerificationAttempt | None:
    """Последняя нерешённая попытка провайдерской проверки.

    Без окна свежести, в отличие от встроенной: поз тут нет, а ревью Sumsub
    (включая ручное) может занять больше СРОК_ЗАДАНИЯ — вердикт обязан
    приземлиться в ту же строку, а не потеряться.
    """
    result = await session.execute(
        select(VerificationAttempt)
        .where(
            VerificationAttempt.user_id == user_id,
            VerificationAttempt.provider == "sumsub",
            VerificationAttempt.status == "issued",
        )
        .order_by(VerificationAttempt.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _отказов_за_сутки(session: AsyncSession, user_id: str) -> int:
    сутки_назад = datetime.now(timezone.utc) - timedelta(hours=24)
    result = await session.execute(
        select(func.count(VerificationAttempt.id)).where(
            VerificationAttempt.user_id == user_id,
            VerificationAttempt.status == "rejected",
            VerificationAttempt.created_at >= сутки_назад,
        )
    )
    return int(result.scalar() or 0)


async def _фото_анкеты(session: AsyncSession, user_id: str) -> list[str]:
    result = await session.execute(select(Profile).where(Profile.user_id == user_id))
    профиль = result.scalar_one_or_none()
    return as_list(профиль.photos) if профиль else []


async def _скачать_референс(url: str) -> bytes:
    """Первое фото анкеты — сервер сам забирает его из R2.

    Клиенту референс не доверяем: пришли он «своё фото анкеты», сравнение
    превратилось бы в сравнение подделки с подделкой.
    """
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        ответ = await client.get(url)
        ответ.raise_for_status()
        return ответ.content


async def _сверить_остальные_фото(референс: bytes, фото: list[str]) -> dict:
    """Есть ли человек с первого (опорного) фото на остальных фото анкеты.

    Галочка описывает всю анкету, а не первое фото: без этой сверки катфишинг
    прятался бы на второй позиции — своё фото первым, чужие дальше. Сверяются
    публичные фото анкеты между собой, биометрии здесь нет.

    Возвращает:
    * {"ok": True} — на каждом фото найден владелец;
    * {"ok": False, "unavailable": True} — сверка не состоялась (хранилище
      или AI недоступны), решение принимать нельзя;
    * {"ok": False, "index": i, "reason": ...} — на i-м фото владельца нет.
    """
    for i, url in enumerate(фото[1:], start=1):
        try:
            другое = await _скачать_референс(url)
        except Exception as exc:
            logger.error(f"Сверка фото анкеты: не скачалось фото №{i + 1}: {exc}")
            return {"ok": False, "unavailable": True}
        вердикт = await verify_person_in_photo(референс, другое)
        del другое
        if вердикт.get("unavailable"):
            return {"ok": False, "unavailable": True}
        if not вердикт.get("present"):
            return {"ok": False, "index": i, "reason": вердикт.get("reason", "")}
    return {"ok": True}


async def _страйк_за_чужое_лицо(
    session: AsyncSession, user: User, content: str, reason: str
) -> JSONResponse | None:
    """Страйк «на проверке чужое лицо» с эскалацией в бан.

    Обёртка над register_identity_strike с типом verification_identity —
    см. services/enforcement.py: там же лимит и окно. Возвращает готовый
    403-ответ, если бан применён (вызывающий обязан вернуть его как есть:
    JSONResponse коммитит сессию, исключение откатило бы сам бан).
    """
    return await register_identity_strike(
        session, user, "verification_identity", content, reason
    )


def _только_встроенный_режим() -> None:
    """Встроенные позы закрыты, пока включён провайдер.

    Иначе провайдерская проверка обходится: человек бьёт в старые эндпоинты
    и получает галочку встроенной схемой, хотя продукт обещает уровень Sumsub.
    """
    if settings.sumsub_enabled:
        raise HTTPException(
            status_code=409,
            detail="Проверка выполняется через провайдера — обновите приложение",
        )


def _только_провайдер() -> None:
    """Провайдерские эндпоинты без ключей Sumsub не существуют."""
    if not settings.sumsub_enabled:
        raise HTTPException(status_code=404, detail="Провайдер проверки не подключён")


def _секунд_до_истечения(задание: VerificationAttempt) -> int:
    выдано = задание.created_at
    if выдано.tzinfo is None:
        выдано = выдано.replace(tzinfo=timezone.utc)
    осталось = (выдано + СРОК_ЗАДАНИЯ) - datetime.now(timezone.utc)
    return max(0, int(осталось.total_seconds()))


@router.get("/status")
async def verification_status(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Состояние проверки для UI: галочка, остаток попыток, живое задание."""
    провайдер = "sumsub" if settings.sumsub_enabled else "builtin"
    отказов = await _отказов_за_сутки(session, user.id)
    задание = None
    ждёт_провайдера = False
    if not user.is_verified:
        if провайдер == "builtin":
            задание = await _активное_задание(session, user.id)
        else:
            # Есть начатая провайдерская попытка без вердикта — UI по этому
            # флагу сразу опрашивает /sumsub/finalize, а не ждёт нажатия.
            ждёт_провайдера = await _выданная_sumsub(session, user.id) is not None
    фото = [] if user.is_verified else await _фото_анкеты(session, user.id)
    return {
        "is_verified": user.is_verified,
        "attempts_left": max(0, СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ - отказов),
        # Без фото анкеты проверка не имеет смысла — не с чем сравнивать.
        # UI по этому флагу ведёт человека сначала к загрузке фото.
        "has_photo": bool(фото) or user.is_verified,
        # Кто проверяет: "builtin" — позы + GLM, "sumsub" — WebSDK провайдера.
        "provider": провайдер,
        "provider_pending": ждёт_провайдера,
        "challenge": (
            {
                "id": задание.id,
                "poses": задание.poses or [],
                "expires_in": _секунд_до_истечения(задание),
            }
            if задание
            else None
        ),
    }


@router.post("/challenge")
async def issue_challenge(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Выдать задание: анфас + случайные позы. Живое задание переиспользуется."""
    _только_встроенный_режим()
    if user.is_verified:
        raise HTTPException(status_code=409, detail="Профиль уже подтверждён")

    отказов = await _отказов_за_сутки(session, user.id)
    if отказов >= СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ:
        raise HTTPException(
            status_code=429,
            detail="Слишком много неудачных попыток — вернитесь к проверке завтра",
        )

    if not await _фото_анкеты(session, user.id):
        raise HTTPException(
            status_code=400,
            detail="Сначала добавьте фото в анкету — с ним сравниваем лицо",
        )

    # Живое задание не перевыпускаем: обновление страницы не должно позволять
    # крутить позы, пока не выпадут удобные для заготовленной записи
    задание = await _активное_задание(session, user.id)
    if задание is None:
        задание = VerificationAttempt(
            user_id=user.id,
            poses=[ПОЗА_АНФАС] + random.sample(ПОЗЫ_ПУЛ, СЛУЧАЙНЫХ_ПОЗ),
            status="issued",
        )
        session.add(задание)
        await session.flush()
        # server_default now() проставляется базой — забираем его, иначе
        # created_at пуст и посчитать expires_in нечем
        await session.refresh(задание)

    return {
        "id": задание.id,
        "poses": задание.poses or [],
        "expires_in": _секунд_до_истечения(задание),
        "attempts_left": max(0, СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ - отказов),
    }


@router.post("/submit")
async def submit_verification(
    frames: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Принять кадры по заданию и решить судьбу галочки.

    Кадры обрабатываются в памяти и не сохраняются: см. докстринг модуля.
    """
    _только_встроенный_режим()
    if user.is_verified:
        raise HTTPException(status_code=409, detail="Профиль уже подтверждён")

    отказов = await _отказов_за_сутки(session, user.id)
    if отказов >= СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ:
        raise HTTPException(
            status_code=429,
            detail="Слишком много неудачных попыток — вернитесь к проверке завтра",
        )

    задание = await _активное_задание(session, user.id)
    if задание is None:
        # 410, а не 404: задание было, но истекло (или не выдавалось) —
        # клиент по этому коду молча берёт новое и продолжает
        raise HTTPException(
            status_code=410,
            detail="Задание истекло — начните проверку заново",
        )

    позы: list[str] = задание.poses or []
    if len(frames) != len(позы):
        raise HTTPException(
            status_code=400,
            detail=f"Нужно ровно {len(позы)} кадра — по одному на каждую позу",
        )

    кадры: list[bytes] = []
    for кадр_файл in frames:
        if not кадр_файл.content_type or not кадр_файл.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Кадры должны быть изображениями")
        содержимое = await кадр_файл.read()
        if len(содержимое) > КАДР_МАКС_БАЙТ:
            raise HTTPException(status_code=400, detail="Кадр слишком большой (макс 5 МБ)")
        # Та же санитизация, что у фото профиля: перекодирование отсекает
        # не-картинки и срезает метаданные ещё до того, как байты уйдут в AI
        try:
            содержимое, _, _ = sanitize_image(содержимое)
        except ImageRejected as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        кадры.append(содержимое)

    референс: bytes | None = None
    фото: list[str] = []
    профиль: Profile | None = None
    if len(set(кадры)) < len(кадры):
        # Байт-в-байт одинаковые кадры живая съёмка не даёт никогда: шум
        # сенсора и перекодирование делают каждый снимок уникальным.
        # Дубликат — это один файл, присланный по разу на позу мимо клиента;
        # вердикт очевиден без AI, попытка сжигается как обычный отказ.
        вердикт: dict = {"live": False, "reason": "duplicate frames"}
    else:
        result = await session.execute(select(Profile).where(Profile.user_id == user.id))
        профиль = result.scalar_one_or_none()
        фото = as_list(профиль.photos) if профиль else []
        if not фото:
            raise HTTPException(
                status_code=400,
                detail="Сначала добавьте фото в анкету — с ним сравниваем лицо",
            )
        try:
            референс = await _скачать_референс(фото[0])
        except Exception as exc:
            # Хранилище фото недоступно — вина сервиса, задание не сжигаем
            logger.error(f"Верификация: не скачалось фото анкеты: {exc}")
            raise HTTPException(
                status_code=503,
                detail="Не получилось свериться с фото анкеты — попробуйте через пару минут",
            ) from exc

        вердикт = await verify_liveness(
            кадры, референс, [ОПИСАНИЕ_ПОЗ_EN.get(п, п) for п in позы]
        )
    # Кадры — биометрия, дальше они не нужны: не держим на них ссылок дольше
    # необходимого. Референс — публичное фото анкеты, он ещё нужен для сверки
    # остальных фото при одобрении.
    del кадры

    if вердикт.get("unavailable"):
        # Проверка не состоялась: задание остаётся issued, человек повторит
        # отправку по нему же. В журнал — как warning, чтобы всплеск таких
        # записей был виден админке.
        await log_moderation(
            user.id, "verification", f"liveness poses={','.join(позы)}",
            {"safe": False, "blocked": False, "reason": вердикт.get("reason", "")},
        )
        raise HTTPException(
            status_code=503,
            detail="Проверка сейчас недоступна — попробуйте через пару минут",
        )

    одобрено = all(
        bool(вердикт.get(к))
        for к in ("live", "real_face", "poses_match", "same_person", "matches_profile")
    )
    задание.decided_at = datetime.now(timezone.utc)

    if одобрено:
        # Прежде чем ставить галочку — остальные фото анкеты: живая съёмка
        # подтвердила только первое, а бейдж читается как «вся анкета настоящая»
        assert референс is not None  # одобрение без референса невозможно
        сверка = await _сверить_остальные_фото(референс, фото)
        del референс
        if not сверка["ok"] and сверка.get("unavailable"):
            # Сверка не состоялась — задание остаётся issued, человек повторит
            raise HTTPException(
                status_code=503,
                detail="Проверка сейчас недоступна — попробуйте через пару минут",
            )
        if not сверка["ok"]:
            причина = (
                f"На фото №{сверка['index'] + 1} не найден человек, прошедший проверку — "
                "уберите из анкеты чужие фотографии"
            )
            задание.status = "rejected"
            задание.reason = причина
            бан = await _страйк_за_чужое_лицо(
                session, user, фото[сверка["index"]], сверка.get("reason", "")
            )
            if бан is not None:
                return бан
            return JSONResponse(
                status_code=422,
                content={
                    "detail": причина,
                    "attempts_left": max(0, СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ - (отказов + 1)),
                },
            )

        задание.status = "approved"
        задание.reason = ""
        user.is_verified = True
        # Опорное фото: пока оно в анкете, новые фото сверяются с ним
        # (routers/profiles.py); убрали его — галочка снимается
        if профиль is not None:
            профиль.verified_photo = фото[0]
        await log_moderation(
            user.id, "verification", f"liveness poses={','.join(позы)}",
            {"safe": True, "blocked": False, "reason": вердикт.get("reason", "")},
        )
        return {"verified": True}

    причина = _человеческая_причина(вердикт)
    задание.status = "rejected"
    задание.reason = причина
    await log_moderation(
        user.id, "verification", f"liveness poses={','.join(позы)}",
        {"safe": False, "blocked": True, "reason": вердикт.get("reason", "")},
    )
    # Живая съёмка честная (настоящий живой человек, один на всех кадрах),
    # но лицо не то, что в анкете, — это сигнатура катфишинга, а не неудачный
    # кадр. Страйк; несколько таких — бан (см. _страйк_за_чужое_лицо).
    if (
        bool(вердикт.get("live"))
        and bool(вердикт.get("real_face"))
        and bool(вердикт.get("same_person"))
        and not вердикт.get("matches_profile")
    ):
        бан = await _страйк_за_чужое_лицо(
            session, user, f"liveness poses={','.join(позы)}", вердикт.get("reason", "")
        )
        if бан is not None:
            return бан
    # ВАЖНО: 422 отдаётся JSONResponse'ом, а не HTTPException: get_session
    # коммитит на чистом возврате и откатывает на исключении — а отказ обязан
    # сохраниться, иначе суточный лимит не считается и перебор бесплатен
    return JSONResponse(
        status_code=422,
        content={
            "detail": причина,
            "attempts_left": max(0, СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ - (отказов + 1)),
        },
    )


# ═══════════════════ Провайдерский режим (Sumsub) ═══════════════════
#
# Поток: клиент берёт токен → проходит WebSDK Sumsub (съёмку и анти-дипфейк
# делает провайдер) → вердикт приходит вебхуком И/ИЛИ опросом /sumsub/finalize.
# GREEN провайдера — ещё не галочка: Sumsub не знает, чьи фото стоят в анкете,
# поэтому сервер скачивает один кадр селфи из заявки, в памяти сверяет лицо
# с фото анкеты (verify_face_match) и только после совпадения ставит
# is_verified. Кадр нигде не сохраняется — та же доктрина, что у встроенной
# схемы. Суточный лимит отказов общий на оба режима.


async def _решить_sumsub(
    session: AsyncSession,
    user: User,
    задание: VerificationAttempt | None,
    applicant_id: str,
    review_answer: str,
    reject_type: str,
    moderation_comment: str,
) -> dict:
    """Применить вердикт Sumsub к пользователю.

    Возвращает {"outcome": ..., "reason": str}, где outcome:
    * "approved" — галочка поставлена (или уже стояла);
    * "rejected" — отказ, причина человеку в reason;
    * "banned" — отказ перерос в блокировку: лицо систематически чужое
      (см. _страйк_за_чужое_лицо), аккаунт заблокирован;
    * "pending" — Sumsub ещё не решил;
    * "no_photo" — сверять не с чем, анкета без фото;
    * "unavailable" — сверка не состоялась (Sumsub/хранилище/AI легли),
      попытка НЕ сожжена, вердикт применится при следующей доставке.

    Идемпотентно: повторный вебхук по уже решённому не создаёт новых строк —
    на GREEN выходит через is_verified, на RED без выданной попытки ничего
    не пишет (иначе ретраи доставки жгли бы суточный лимит по кругу).
    """
    if user.is_verified:
        return {"outcome": "approved", "reason": ""}

    if review_answer == "GREEN":
        result = await session.execute(select(Profile).where(Profile.user_id == user.id))
        профиль = result.scalar_one_or_none()
        фото = as_list(профиль.photos) if профиль else []
        if not фото:
            return {"outcome": "no_photo", "reason": ""}
        try:
            селфи = await sumsub.best_selfie_frame(applicant_id)
        except sumsub.SumsubUnavailable:
            return {"outcome": "unavailable", "reason": "sumsub down"}
        if селфи is None:
            # GREEN без единого кадра селфи — уровень в дашборде собран без
            # шага Liveness. Это конфигурационная авария, а не вина человека.
            logger.error(
                f"Sumsub GREEN без селфи (applicant={applicant_id}) — "
                "проверьте шаги уровня в дашборде"
            )
            return {"outcome": "unavailable", "reason": "no selfie in applicant"}
        try:
            референс = await _скачать_референс(фото[0])
        except Exception as exc:
            logger.error(f"Sumsub-сверка: не скачалось фото анкеты: {exc}")
            return {"outcome": "unavailable", "reason": "profile photo unreachable"}

        вердикт = await verify_face_match(селфи, референс)
        # Селфи — биометрия, дальше не нужна; референс — публичное фото
        # анкеты, он ещё пригодится для сверки остальных фото
        del селфи

        if вердикт.get("unavailable"):
            del референс
            await log_moderation(
                user.id, "verification", f"sumsub applicant={applicant_id}",
                {"safe": False, "blocked": False, "reason": вердикт.get("reason", "")},
            )
            return {"outcome": "unavailable", "reason": "face match unavailable"}

        if вердикт.get("matches_profile"):
            # Селфи совпало с первым фото — но галочка описывает всю анкету:
            # остальные фото тоже должны содержать этого человека
            сверка = await _сверить_остальные_фото(референс, фото)
            del референс
            if not сверка["ok"] and сверка.get("unavailable"):
                return {"outcome": "unavailable", "reason": "photo sweep unavailable"}
            if not сверка["ok"]:
                причина = (
                    f"На фото №{сверка['index'] + 1} не найден человек, прошедший "
                    "проверку — уберите из анкеты чужие фотографии"
                )
                if задание is not None:
                    задание.status = "rejected"
                    задание.reason = причина
                    задание.provider_ref = applicant_id
                    задание.decided_at = datetime.now(timezone.utc)
                бан = await _страйк_за_чужое_лицо(
                    session, user, фото[сверка["index"]], сверка.get("reason", "")
                )
                if бан is not None:
                    return {"outcome": "banned", "reason": причина}
                return {"outcome": "rejected", "reason": причина}

            if задание is None:
                # Вердикт пережил окно попытки (ручное ревью бывает долгим) —
                # строка для истории всё равно нужна
                задание = VerificationAttempt(
                    user_id=user.id, poses=[], status="issued", provider="sumsub"
                )
                session.add(задание)
            задание.status = "approved"
            задание.reason = ""
            задание.provider_ref = applicant_id
            задание.decided_at = datetime.now(timezone.utc)
            # Вердикт часто приходит вебхуком, когда шторка уже закрыта —
            # человек узнаёт о галочке из центра уведомлений. Дубля не будет:
            # повторный вебхук по верифицированному отсекает выход в начале
            # функции, досюда доходят только ставящие галочку впервые
            await записать_уведомление(session, user.id, "verification_approved", {})
            user.is_verified = True
            # Опорное фото: пока оно в анкете, новые фото сверяются с ним
            # (routers/profiles.py); убрали его — галочка снимается
            if профиль is not None:
                профиль.verified_photo = фото[0]
            await log_moderation(
                user.id, "verification", f"sumsub applicant={applicant_id}",
                {"safe": True, "blocked": False, "reason": вердикт.get("reason", "")},
            )
            return {"outcome": "approved", "reason": ""}

        del референс
        причина = "Лицо на кадрах не совпало с фото анкеты"
        await log_moderation(
            user.id, "verification", f"sumsub applicant={applicant_id}",
            {"safe": False, "blocked": True, "reason": вердикт.get("reason", "")},
        )
        if задание is not None:
            задание.status = "rejected"
            задание.reason = причина
            задание.provider_ref = applicant_id
            задание.decided_at = datetime.now(timezone.utc)
        # Живость и анти-дипфейк уже подтвердил Sumsub (GREEN) — селфи снял
        # настоящий живой человек, и лицо у него не то, что в анкете.
        # Та же сигнатура катфишинга, что во встроенном режиме.
        бан = await _страйк_за_чужое_лицо(
            session, user, f"sumsub applicant={applicant_id}", вердикт.get("reason", "")
        )
        if бан is not None:
            return {"outcome": "banned", "reason": причина}
        return {"outcome": "rejected", "reason": причина}

    if review_answer == "RED":
        # moderationComment — формулировка Sumsub для человека (язык задаётся
        # в их дашборде); без неё — свой текст. clientComment сюда не идёт
        # никогда: он внутренний.
        причина = (moderation_comment or "").strip() or (
            "Проверка у провайдера не пройдена — попробуйте ещё раз"
        )
        await log_moderation(
            user.id, "verification", f"sumsub applicant={applicant_id}",
            {"safe": False, "blocked": True, "reason": f"RED {reject_type}".strip()},
        )
        if задание is not None:
            задание.status = "rejected"
            задание.reason = причина
            задание.provider_ref = applicant_id
            задание.decided_at = datetime.now(timezone.utc)
        return {"outcome": "rejected", "reason": причина}

    return {"outcome": "pending", "reason": ""}


@router.post("/sumsub/token")
async def sumsub_token(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Токен для WebSDK Sumsub. Заводит попытку, если нерешённой нет."""
    _только_провайдер()
    if user.is_verified:
        raise HTTPException(status_code=409, detail="Профиль уже подтверждён")

    отказов = await _отказов_за_сутки(session, user.id)
    if отказов >= СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ:
        raise HTTPException(
            status_code=429,
            detail="Слишком много неудачных попыток — вернитесь к проверке завтра",
        )

    if not await _фото_анкеты(session, user.id):
        raise HTTPException(
            status_code=400,
            detail="Сначала добавьте фото в анкету — с ним сравниваем лицо",
        )

    задание = await _выданная_sumsub(session, user.id)
    if задание is None:
        задание = VerificationAttempt(
            user_id=user.id, poses=[], status="issued", provider="sumsub"
        )
        session.add(задание)
        await session.flush()

    try:
        токен = await sumsub.create_access_token(user.id)
    except sumsub.SumsubUnavailable as exc:
        # Исключение откатит сессию — свежесозданная попытка не останется
        # висеть, а человек ничего не потерял
        raise HTTPException(
            status_code=503,
            detail="Проверка сейчас недоступна — попробуйте через пару минут",
        ) from exc

    return {
        **токен,
        "attempts_left": max(0, СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ - отказов),
    }


@router.post("/sumsub/finalize")
async def sumsub_finalize(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Опрос вердикта: клиент зовёт после WebSDK, пока не решится.

    Дублирует вебхук нарочно: вебхук приходит в фоне и может не дойти
    (сеть, конфигурация), а человек стоит с открытым экраном и ждёт.
    Оба пути сходятся в _решить_sumsub и идемпотентны.
    """
    _только_провайдер()
    if user.is_verified:
        return {"verified": True}

    try:
        статус = await sumsub.applicant_status(user.id)
    except sumsub.SumsubUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail="Проверка сейчас недоступна — попробуйте через пару минут",
        ) from exc

    if статус is None or not статус["review_answer"]:
        return {"pending": True}

    задание = await _выданная_sumsub(session, user.id)
    итог = await _решить_sumsub(
        session, user, задание,
        статус["applicant_id"], статус["review_answer"],
        статус["reject_type"], статус["moderation_comment"],
    )

    if итог["outcome"] == "approved":
        return {"verified": True}
    if итог["outcome"] == "banned":
        # Бан уже применён в _решить_sumsub — отдать его надо чистым ответом
        # (JSONResponse), исключение откатило бы и сам бан. Код account_banned
        # ведёт клиент на экран блокировки.
        return JSONResponse(
            status_code=403,
            content={
                "detail": "Аккаунт заблокирован: фотографии в анкете не принадлежат владельцу",
                "code": BANNED_CODE,
            },
        )
    if итог["outcome"] == "rejected":
        # Как в /submit: отказ обязан закоммититься, поэтому JSONResponse,
        # а не HTTPException. Счётчик берём заново — свежий отказ уже виден
        # сессии через autoflush.
        отказов = await _отказов_за_сутки(session, user.id)
        return JSONResponse(
            status_code=422,
            content={
                "detail": итог["reason"],
                "attempts_left": max(0, СУТОЧНЫЙ_ЛИМИТ_ОТКАЗОВ - отказов),
            },
        )
    if итог["outcome"] == "no_photo":
        raise HTTPException(
            status_code=400,
            detail="Сначала добавьте фото в анкету — с ним сравниваем лицо",
        )
    if итог["outcome"] == "unavailable":
        raise HTTPException(
            status_code=503,
            detail="Проверка сейчас недоступна — попробуйте через пару минут",
        )
    return {"pending": True}


@router.post("/sumsub/webhook")
async def sumsub_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """Вебхук Sumsub (applicantReviewed). Без авторизации, но с подписью.

    Подпись HMAC считается по СЫРЫМ байтам тела ключом из Webhook manager —
    без неё любой, кто узнал URL, раздавал бы галочки. После подписи отвечаем
    200 всегда: на 5xx Sumsub ретраит доставку, а «сверка не состоялась» у
    нас не теряется — попытка остаётся issued, её добьёт /sumsub/finalize.
    """
    _только_провайдер()
    тело = await request.body()
    if not sumsub.verify_webhook_digest(
        тело,
        request.headers.get("x-payload-digest", ""),
        request.headers.get("x-payload-digest-alg", "HMAC_SHA256_HEX"),
    ):
        raise HTTPException(status_code=401, detail="Bad signature")

    try:
        payload = json.loads(тело)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Bad JSON") from exc

    if payload.get("type") != "applicantReviewed":
        return {"ok": True}
    if payload.get("sandboxMode") and not settings.DEBUG:
        # Песочница провайдера не должна дотягиваться до боевых галочек
        logger.warning("Sumsub: sandbox-вебхук на проде — проигнорирован")
        return {"ok": True}

    external_user_id = payload.get("externalUserId") or ""
    user = await session.get(User, external_user_id) if external_user_id else None
    if user is None:
        logger.warning(f"Sumsub: вебхук о неизвестном пользователе {external_user_id!r}")
        return {"ok": True}

    result = payload.get("reviewResult") or {}
    задание = await _выданная_sumsub(session, user.id)
    итог = await _решить_sumsub(
        session, user, задание,
        payload.get("applicantId") or "",
        result.get("reviewAnswer") or "",
        result.get("reviewRejectType") or "",
        result.get("moderationComment") or "",
    )
    return {"ok": True, "outcome": итог["outcome"]}
