"""Текстовые страйки и автобан для бот-канала.

Зеркало api/services/enforcement.py: нарушения через бота (имя и био при
регистрации, текст лайка, личка) пишутся в тот же журнал модерации и ведут
к тому же бану, что и нарушения через мини-апп. До этого модуля бот только
отказывал сообщением — рекламу можно было слать через бота бесконечно,
не приближаясь к блокировке, а счёт «нарушение N из M» видели только в
мини-аппе.

Правила и лестницы обязаны совпадать с API дословно: счёт один на оба
канала. Числа объявлены «сырыми» литералами (штуки/часы), а не timedelta —
мета-тест в api/tests читает их ast-ом и сверяет с апишными константами,
как это сделано для зеркала моделей: изменение правил в API без правки
здесь роняет тест, а не тихо разъезжается.

Redis общий: отзыв токенов пишется тем же ключом, который читает API
(services/token_revocation.py), событие «banned» уходит в канал
пользователя — открытый мини-апп покажет экран блокировки. Канал
dating:bot:events НЕ публикуем: хендлер сам отвечает экраном бана в чат,
и дублирующее сообщение от redis_subscriber было бы вторым таким же.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

# database.* импортируется внутри функций: бот-тесты из api/tests подменяют
# database заглушкой-модулем без подмодулей (см. test_identity_enforcement),
# и модульный `from database.connection import ...` ронял бы весь enforcement
# на импорте, а не при вызове.

logger = logging.getLogger(__name__)

#: Правила текстовых страйков: категория → (порог, окно в часах). Порог —
#: счёт blocked-записей журнала этой категории, при котором наступает бан
#: (текущее нарушение уже в журнале и уже в счёте). Обоснования порогов —
#: у апишного TEXT_STRIKE_RULES; здесь только зеркало в сырых числах.
TEXT_STRIKE_RULES_RAW: dict[str, tuple[int, int]] = {
    "ad": (3, 720),
    "heavy": (2, 720),
    "text": (5, 168),
}

#: Лестницы сроков по категориям, в часах; None — вечный бан, последняя
#: ступень повторяется. Только текстовые категории: identity/reports/manual
#: банятся исключительно на стороне API.
BAN_LADDER_HOURS: dict[str, tuple[int | None, ...]] = {
    "ad": (24, 72, 168, None),
    "text": (24, 72, 168, None),
    "heavy": (168, None),
}

#: Причина бана по категории — читает сам забаненный (журнал, экран бана).
TEXT_BAN_REASONS = {
    "ad": "Реклама и ссылки: неоднократные нарушения правил",
    "heavy": "Запрещённый контент: наркотики, платные услуги, мошенничество или угрозы",
    "text": "Оскорбления и запрещённые тексты: неоднократные нарушения правил",
}

#: Записи журнала, обнуляющие счёт страйков (см. апишный AMNESTY_TYPES).
AMNESTY_TYPES = ("unban_purchase", "unban_admin")
#: Лестницу сбрасывает только разбан админом — платный разбан ступень хранит.
LADDER_AMNESTY_TYPES = ("unban_admin",)
#: Тип записи «бан применён» — по ним лестница считает номер бана.
BAN_APPLIED_TYPE = "ban_applied"
#: Окно рецидива лестницы, в часах (180 дней — как BAN_HISTORY_WINDOW в API).
BAN_HISTORY_HOURS = 4320

#: Ключ отзыва токенов — тот же, что _USER_PREFIX в api/services/token_revocation.py.
REVOKED_BEFORE_KEY = "dating:jwt:revoked_before:"
#: TTL отзыва, в часах — дефолт JWT_ACCESS_EXPIRE_HOURS в API: запись должна
#: пережить самый свежий выданный токен. Более длинный TTL безвреден.
REVOKE_TTL_HOURS = 72

# Производные словари с timedelta — рабочие; сырые выше существуют ради
# ast-сверки и человекочитаемости диффа при изменении правил
TEXT_STRIKE_RULES: dict[str, tuple[int, timedelta]] = {
    категория: (порог, timedelta(hours=окно))
    for категория, (порог, окно) in TEXT_STRIKE_RULES_RAW.items()
}
BAN_LADDERS: dict[str, tuple[timedelta | None, ...]] = {
    категория: tuple(timedelta(hours=ч) if ч is not None else None for ч in часы)
    for категория, часы in BAN_LADDER_HOURS.items()
}


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite в тестах возвращает naive-даты; в проде колонки tz-aware."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def ban_term_text(banned_until: datetime | None) -> str:
    """Человеческий срок для журнала: «навсегда» или «до 21.08.2026 18:00 (UTC)»."""
    if banned_until is None:
        return "навсегда"
    return f"до {banned_until.strftime('%d.%m.%Y %H:%M')} (UTC)"


async def log_moderation(
    user_id: str, content_type: str, content: str, verdict: dict
) -> None:
    """Записать вердикт модерации в общий журнал — тот же, что пишет API.

    Пишем и безопасные проверки: журнал — единственный способ разобрать
    спорную блокировку постфактум. Сессия своя и короткая; сбой записи не
    ломает сценарий — пользователь не виноват, что журнал недоступен.
    """
    result = "blocked" if verdict.get("blocked") else (
        "safe" if verdict.get("safe", True) else "warning"
    )
    try:
        from database.connection import _session_cls
        from database.models import AiModerationLog

        Session = _session_cls()
        async with Session() as session:
            session.add(
                AiModerationLog(
                    user_id=user_id,
                    content_type=content_type,
                    # Длинные тексты режем: журналу нужен повод, а не весь контент
                    content=(content or "")[:2000],
                    result=result,
                    action="none",
                    category=verdict.get("category", "") or "",
                    reason=verdict.get("reason", "") or "",
                )
            )
            await session.commit()
    except Exception as e:
        logger.error(f"Не удалось записать лог модерации из бота: {e}")


async def text_strike_count(user_id: str, category: str, window: timedelta) -> int:
    """Сколько blocked-текстов этой категории набралось за окно.

    Копия апишного text_strike_count: окно обрезается последним разбаном
    (AMNESTY_TYPES), сбой журнала — 0: лучше пропустить эскалацию, чем
    банить по фантомному счёту.
    """
    граница = datetime.now(timezone.utc) - window
    try:
        from database.connection import _session_cls
        from database.models import AiModerationLog

        Session = _session_cls()
        async with Session() as session:
            result = await session.execute(
                select(func.max(AiModerationLog.created_at)).where(
                    AiModerationLog.user_id == user_id,
                    AiModerationLog.content_type.in_(AMNESTY_TYPES),
                )
            )
            разбан = _aware(result.scalar())
            if разбан is not None and разбан > граница:
                граница = разбан

            result = await session.execute(
                select(func.count(AiModerationLog.id)).where(
                    AiModerationLog.user_id == user_id,
                    AiModerationLog.category == category,
                    AiModerationLog.result == "blocked",
                    AiModerationLog.created_at >= граница,
                )
            )
            return int(result.scalar() or 0)
    except Exception as e:
        logger.error(f"Не удалось посчитать текстовые страйки: {e}")
        return 0


async def prior_ban_count(user_id: str) -> int:
    """Который это бан по счёту — число ban_applied за окно рецидива.

    Копия апишного prior_ban_count: окно обрезает только разбан админом,
    сбой журнала — 0 (первая ступень вместо эскалации, ошибка в мягкую
    сторону).
    """
    граница = datetime.now(timezone.utc) - timedelta(hours=BAN_HISTORY_HOURS)
    try:
        from database.connection import _session_cls
        from database.models import AiModerationLog

        Session = _session_cls()
        async with Session() as session:
            result = await session.execute(
                select(func.max(AiModerationLog.created_at)).where(
                    AiModerationLog.user_id == user_id,
                    AiModerationLog.content_type.in_(LADDER_AMNESTY_TYPES),
                )
            )
            амнистия = _aware(result.scalar())
            if амнистия is not None and амнистия > граница:
                граница = амнистия

            result = await session.execute(
                select(func.count(AiModerationLog.id)).where(
                    AiModerationLog.user_id == user_id,
                    AiModerationLog.content_type == BAN_APPLIED_TYPE,
                    AiModerationLog.created_at >= граница,
                )
            )
            return int(result.scalar() or 0)
    except Exception as e:
        logger.error(f"Не удалось посчитать прошлые баны: {e}")
        return 0


def _dialect_insert(session):
    """INSERT .. ON CONFLICT нужного диалекта — как в api/services/ban_memory.py."""
    if session.bind is not None and session.bind.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        return sqlite_insert
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    return pg_insert


async def _remember_ban(
    session, telegram_id: int | None, apple_id: str | None,
    reason: str, banned_until: datetime | None,
) -> None:
    """Память банов, переживающая удаление аккаунта — копия api remember_ban.

    Сначала UPDATE (повторный бан обязан удлинить срок в существующей
    строке), затем INSERT для новой привязки; on_conflict_do_nothing гасит
    гонку двух одновременных банов.
    """
    from sqlalchemy import or_, update as sa_update

    from database.models import BannedIdentity

    reason = reason[:500]
    rows: list[dict] = []
    if telegram_id:
        rows.append({"telegram_id": telegram_id, "apple_id": None})
    if apple_id:
        rows.append({"telegram_id": None, "apple_id": apple_id})
    if not rows:
        # Личность без внешних привязок (гость по коду) — блокировать нечего
        return

    условия = []
    if telegram_id:
        условия.append(BannedIdentity.telegram_id == telegram_id)
    if apple_id:
        условия.append(BannedIdentity.apple_id == apple_id)
    await session.execute(
        sa_update(BannedIdentity)
        .where(or_(*условия))
        .values(reason=reason, banned_until=banned_until)
    )

    insert = _dialect_insert(session)
    for row in rows:
        await session.execute(
            insert(BannedIdentity)
            .values(reason=reason, banned_until=banned_until, **row)
            .on_conflict_do_nothing()
        )


async def _revoke_tokens(user_id: str) -> None:
    """Отозвать токены мини-аппа тем же Redis-ключом, что api/token_revocation.

    Без отзыва открытый WebSocket пережил бы бан: HTTP-запросы отсекает
    проверка is_banned, а сокет между сообщениями её не переспрашивает.
    """
    try:
        from services.redis_subscriber import _get_redis

        r = await _get_redis()
        now_ts = int(datetime.now(timezone.utc).timestamp())
        await r.set(
            f"{REVOKED_BEFORE_KEY}{user_id}", str(now_ts),
            ex=REVOKE_TTL_HOURS * 3600,
        )
    except Exception as e:
        logger.error(f"Отзыв токенов из бота не удался (user={user_id}): {e}")


async def _publish_banned(
    user_id: str, reason: str, banned_until: datetime | None
) -> None:
    """Сообщить открытому мини-аппу о бане — лучшая попытка, бан уже состоялся."""
    try:
        from services.redis_subscriber import _get_redis

        r = await _get_redis()
        await r.publish(
            f"dating:user:{user_id}",
            json.dumps({
                "type": "banned",
                "reason": reason,
                "banned_until": banned_until.isoformat() if banned_until else None,
            }),
        )
    except Exception as e:
        logger.warning(f"Событие о бане не опубликовано (user={user_id}): {e}")


async def ban_user_for_violation(
    user_id: str, reason: str, category: str
) -> tuple[bool, datetime | None]:
    """Заблокировать пользователя за нарушение, пойманное ботом.

    Та же механика, что у апишного ban_user_for_violation: срок из лестницы
    категории по числу прошлых банов, флаг на пользователе, память банов,
    отзыв токенов, событие мини-аппу. Сессия своя с немедленным коммитом —
    у бота нет сессии запроса, которую мог бы откатить чужой сбой.

    Возвращает (применён ли бан, срок). Админов и владельцев автоматика
    не трогает — их случай разбирает живой владелец.
    """
    banned_until: datetime | None = None
    try:
        from database.connection import _session_cls
        from database.models import User

        Session = _session_cls()
        async with Session() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user is None:
                return False, None
            if user.role in ("admin", "owner"):
                logger.warning(
                    f"Автобан пропущен: пользователь {user_id} имеет роль "
                    f"{user.role} ({reason})"
                )
                return False, None

            лестница = BAN_LADDERS.get(category, (None,))
            ступень = min(await prior_ban_count(user_id), len(лестница) - 1)
            срок = лестница[ступень]
            banned_until = datetime.now(timezone.utc) + срок if срок else None

            user.is_banned = True
            user.banned_until = banned_until
            await _remember_ban(
                session,
                telegram_id=user.telegram_id,
                apple_id=user.apple_id,
                reason=reason,
                banned_until=banned_until,
            )
            await session.commit()
    except Exception as e:
        logger.error(f"Автобан из бота не применён (user={user_id}): {e}")
        return False, None

    # Журнал «бан применён» — после коммита бана: по нему следующая лестница
    # выберет ступень выше; его сбой оставит счёт рецидива ниже — мягкая сторона
    await log_moderation(
        user_id,
        BAN_APPLIED_TYPE,
        category,
        {"blocked": True, "reason": f"{reason} — {ban_term_text(banned_until)}"},
    )
    await _revoke_tokens(user_id)
    await _publish_banned(user_id, reason, banned_until)

    logger.warning(
        f"Автобан из бота: пользователь {user_id} заблокирован "
        f"{ban_term_text(banned_until)} — {reason} (категория {category})"
    )
    return True, banned_until


@dataclass
class TextStrikeOutcome:
    """Итог текстового страйка — что случилось и что сказать человеку.

    Зеркало апишного TextStrikeOutcome: хендлер по banned выбирает между
    экраном блокировки и прежним отказом со счётом.
    """

    category: str
    count: int
    limit: int
    banned: bool
    banned_until: datetime | None

    def warning_text(self) -> str:
        """Счёт для предупреждения: «Нарушение 2 из 3 — при 3 блокировка»."""
        return (
            f"Нарушение {self.count} из {self.limit} — "
            f"при {self.limit} аккаунт будет заблокирован."
        )


async def register_text_strike(user_id: str, verdict: dict) -> TextStrikeOutcome | None:
    """Посчитать текстовый страйк и забанить, если категория дошла до порога.

    Контракт апишного register_text_strike: вызывается ПОСЛЕ log_moderation
    с тем же вердиктом — текущее нарушение уже в журнале и уже в счёте.
    None — вердикт safe или без правила.
    """
    if not verdict.get("blocked"):
        return None
    category = verdict.get("category") or "text"
    правило = TEXT_STRIKE_RULES.get(category)
    if правило is None:
        return None
    limit, window = правило

    count = await text_strike_count(user_id, category, window)
    if count < limit:
        return TextStrikeOutcome(
            category=category, count=count, limit=limit,
            banned=False, banned_until=None,
        )

    banned, banned_until = await ban_user_for_violation(
        user_id, TEXT_BAN_REASONS[category], category
    )
    # False — админ/владелец или сбой: остаётся обычным отказом со счётом
    return TextStrikeOutcome(
        category=category, count=count, limit=limit,
        banned=banned, banned_until=banned_until if banned else None,
    )


async def apply_text_strike(
    user_id: str | None, content_type: str, content: str, verdict: dict
) -> TextStrikeOutcome | None:
    """Журнал + страйк одним вызовом — для хендлеров бота.

    user_id может быть None (RegistrationMiddleware не смог создать
    пользователя) — тогда деградируем до прежнего поведения: отказ без
    журнала и счёта, жёсткая стена остаётся на стороне API.
    """
    if not user_id:
        return None
    await log_moderation(user_id, content_type, content, verdict)
    return await register_text_strike(user_id, verdict)


def strike_suffix(исход: TextStrikeOutcome | None) -> str:
    """Довесок «Нарушение N из M» к прежнему тексту отказа ("" — счёта нет)."""
    return f" {исход.warning_text()}" if исход is not None else ""


async def answer_ban_screen(message, reason: str, banned_until: datetime | None) -> None:
    """Экран блокировки сразу после автобана — тем же текстом, что бан-гейт.

    Следующие апдейты забаненного перехватит middlewares/ban_gate.py; этот
    ответ нужен, чтобы человек узнал о бане в момент нарушения, а не от
    молчаливо «сломавшегося» бота. Импорты локальные: enforcement — сервис,
    и тянуть тексты с клавиатурами на уровень модуля значило бы завязать
    сервисный слой на презентацию.
    """
    from config import UNBAN_PRICE_RUB
    from keyboards import unban_kb
    import texts as T

    try:
        await message.answer(
            T.ban_notice(
                UNBAN_PRICE_RUB,
                reason=reason,
                until_iso=banned_until.isoformat() if banned_until else None,
            ),
            reply_markup=unban_kb(UNBAN_PRICE_RUB),
        )
    except Exception as e:
        logger.warning(f"Не удалось показать экран бана: {e}")
