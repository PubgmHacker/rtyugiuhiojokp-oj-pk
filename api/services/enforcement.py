"""Автоматическая блокировка за нарушения, пойманные проверками.

Та же механика, что у ручного бана в admin.py: флаг на пользователе, память
банов (переживает удаление аккаунта), отзыв токенов (убивает и WebSocket),
уведомление боту через Redis. Здесь она собрана в одну функцию, чтобы бан за
катфишинг (чужие фото в анкете, подмена лица на верификации) невозможно было
применить наполовину — например, выставить флаг, но забыть отозвать токены.

Срок бана считает лестница (BAN_LADDERS): первое нарушение категории — короткий
бан, каждый следующий длиннее, конец лестницы — вечный. Ступень выбирается по
числу прошлых банов в журнале модерации, а не по полю на пользователе: журнал
переживает и откат запроса, и удаление аккаунта не трогает (у записей CASCADE,
но вернувшийся наследует срок через память банов, а не через журнал).

Вызывающий обязан отвечать прямым JSONResponse, а не исключением: get_session
коммитит только чистый выход из обработчика, HTTPException откатил бы и сам бан.
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import User
from services.ban_memory import forgive, remember_ban
from services.token_revocation import revoke_all_for_user

logger = logging.getLogger(__name__)

#: Типы записей журнала модерации, которые считаются «страйком за чужое лицо»:
#: photo_identity — новое фото анкеты, где нет человека с опорного фото;
#: verification_identity — живая съёмка честная, но лицо не совпало с анкетой.
IDENTITY_STRIKE_TYPES = ("photo_identity", "verification_identity")
#: Сколько страйков за окно превращаются в бан. Не с первого: несовпадение
#: бывает невинным (старое фото, другая причёска, слабый кадр), и ложный бан
#: живого человека дороже, чем лишняя попытка катфишера. Третий отказ подряд —
#: это уже не «плохой свет», а систематическая подмена личности.
IDENTITY_STRIKE_LIMIT = 3
IDENTITY_STRIKE_WINDOW = timedelta(days=30)
#: Записи журнала, обнуляющие счёт страйков: unban_purchase — платная
#: досрочная разблокировка (бот, handlers/unban.py), unban_admin — разбан в
#: админке. Без амнистии разбан был бы ловушкой: старые страйки никуда не
#: деваются, и первый же спорный кадр возвращал бы бан немедленно.
AMNESTY_TYPES = ("unban_purchase", "unban_admin")

#: Тип записи журнала «бан применён» — по этим записям лестница считает,
#: который это бан по счёту. Пишется в ban_user_for_violation своей сессией,
#: поэтому переживает любой откат запроса.
BAN_APPLIED_TYPE = "ban_applied"
#: Окно рецидива: баны старше не двигают лестницу. Полгода — достаточно, чтобы
#: систематический нарушитель дошёл до вечного бана, и достаточно коротко,
#: чтобы сорвавшийся однажды год назад начинал с первой ступени.
BAN_HISTORY_WINDOW = timedelta(days=180)
#: Лестницу сбрасывает ТОЛЬКО разбан админом: живой человек посмотрел и решил,
#: что бан был лишним — историю чистим. Платный разбан (unban_purchase) снимает
#: текущий бан, но ступень сохраняет: иначе 349 ₽ покупали бы не досрочный
#: выход, а вечный сброс счётчика, и лестница никогда не доходила бы до верха.
LADDER_AMNESTY_TYPES = ("unban_admin",)

#: Лестницы сроков по категориям нарушений. None — вечный бан; последняя
#: ступень повторяется для всех последующих нарушений.
#:
#: Сроки выбраны глазами нарушителя, а не модератора: 24 часа — «до завтра»,
#: почти все ждут; 72 часа — на грани, ждут только привязанные к своим мэтчам;
#: 7 дней — большинство не вернётся само. Поэтому длинные сроки стоят только
#: в конце лестниц и в тяжёлых категориях, а на экране бана всегда виден
#: платный досрочный выход: нарушитель должен выбирать между «подождать» и
#: «заплатить», а не между «подождать» и «удалить приложение».
BAN_LADDERS: dict[str, tuple[timedelta | None, ...]] = {
    # Реклама, ссылки, чужие юзернеймы в анкете (тексты и фото). Первые два
    # нарушения наказываются без бана (отказ + предупреждение + автоочистка
    # поля — см. register_text_strike и TEXT_STRIKE_RULES), сюда доходит
    # третье и дальше.
    "ad": (timedelta(hours=24), timedelta(hours=72), timedelta(days=7), None),
    # Спам и грязь в сообщениях/подписях — то, что ловит текстовая модерация.
    "text": (timedelta(hours=24), timedelta(hours=72), timedelta(days=7), None),
    # Тяжёлое: наркотики, интим-услуги, скам, угрозы. Сразу неделя: короткий
    # бан здесь читается как «можно», а вечный с первого раза не оставляет
    # права на ошибку классификатору.
    "heavy": (timedelta(days=7), None),
    # Автобан по жалобам: 5 независимых жалобщиков, с которыми человек
    # реально взаимодействовал (routers/report.py). Порог высокий, поэтому
    # и первая ступень длинная.
    "reports": (timedelta(days=7), None),
    # Контент, снятый по жалобам (ролики, истории, комментарии) — накопил
    # страйки автором (А2).
    "content": (timedelta(hours=24), timedelta(hours=72), timedelta(days=7), None),
    # Катфишинг — вечный сразу: подмена личности не «нарушение поведения»,
    # а обман в самой сути анкеты. Прежнее поведение.
    "identity": (None,),
    # Ручной бан админом и всё неклассифицированное — вечный, как раньше.
    # Админка может передать явный срок мимо лестницы (duration_hours).
    "manual": (None,),
}


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite в тестах возвращает naive-даты; в проде колонки tz-aware."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def ban_term_text(banned_until: datetime | None) -> str:
    """Человеческий срок для уведомлений: «навсегда» или «до 21.08 18:00 (UTC)»."""
    if banned_until is None:
        return "навсегда"
    return f"до {banned_until.strftime('%d.%m.%Y %H:%M')} (UTC)"


async def identity_strikes(user_id: str) -> int:
    """Сколько страйков за чужое лицо набрал пользователь за окно.

    Считаем по журналу модерации: он пишется в собственной сессии и переживает
    откат запроса (отказ фото — это как раз HTTPException с откатом), поэтому
    счёт честный. Читаем тоже своей сессией — сразу после записи страйка,
    из ещё не закоммиченного запроса. Сессия — из журнального пула, той же
    дорогой, что и запись: чтение идёт при ещё удерживаемой сессии запроса,
    и вторая сессия из ОБЩЕГО пула под залпом — самоблокировка (все
    соединения розданы обработчикам, каждый ждёт второе; см.
    log_session_factory).

    Окно обрезается последним разбаном (AMNESTY_TYPES): после разблокировки
    счёт начинается заново, в бан ведут только новые нарушения.
    """
    from database.connection import log_session_factory
    from models.models import AiModerationLog

    граница = datetime.now(timezone.utc) - IDENTITY_STRIKE_WINDOW
    try:
        async with log_session_factory()() as session:
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
                    AiModerationLog.content_type.in_(IDENTITY_STRIKE_TYPES),
                    AiModerationLog.result == "blocked",
                    AiModerationLog.created_at >= граница,
                )
            )
            return int(result.scalar() or 0)
    except Exception as e:
        # Журнал недоступен — страйк не считается, бан не срабатывает.
        # Лучше пропустить эскалацию, чем забанить по фантомному счёту.
        logger.error(f"Не удалось посчитать страйки идентичности: {e}")
        return 0


async def prior_ban_count(user_id: str) -> int:
    """Который это бан по счёту: число записей ban_applied за окно рецидива.

    Окно обрезается последним разбаном админа (LADDER_AMNESTY_TYPES — платный
    разбан лестницу НЕ сбрасывает, см. комментарий у константы). Сбой журнала
    считается нулём: нарушитель получит первую ступень вместо эскалации —
    ошибка в мягкую сторону, как у identity_strikes. Сессия — из журнального
    пула, по той же причине, что там: вызов идёт при удерживаемой сессии
    запроса, второй из общего пула здесь быть не должно.
    """
    from database.connection import log_session_factory
    from models.models import AiModerationLog

    граница = datetime.now(timezone.utc) - BAN_HISTORY_WINDOW
    try:
        async with log_session_factory()() as session:
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


#: Правила текстовых страйков: категория → (порог, окно). Порог — счёт
#: blocked-записей журнала этой категории, при котором наступает бан
#: (текущее нарушение уже в журнале и уже в счёте).
#:
#: * ad — 3 за 30 дней: реклама всегда осознанна, но первые две попытки
#:   стоят предупреждения, не бана (заказчик: «бан при 3 и больше»).
#: * heavy — 2 за 30 дней: наркотики/интим-услуги/скам/угрозы. Не с первого:
#:   классификатор ошибается, и один ложный «heavy» на невинной фразе не
#:   должен banить с порога; второй за месяц случайным не бывает.
#: * text — 5 за 7 дней: оскорбления и прочая грязь. Порог мягче, окно
#:   короче: сорваться в переписке может любой, наказуема серия.
TEXT_STRIKE_RULES: dict[str, tuple[int, timedelta]] = {
    "ad": (3, timedelta(days=30)),
    "heavy": (2, timedelta(days=30)),
    "text": (5, timedelta(days=7)),
}

#: Причина бана по категории — уходит в журнал, Redis-события и сообщение
#: бота, то есть её читает сам забаненный.
TEXT_BAN_REASONS = {
    "ad": "Реклама и ссылки: неоднократные нарушения правил",
    "heavy": "Запрещённый контент: наркотики, платные услуги, мошенничество или угрозы",
    "text": "Оскорбления и запрещённые тексты: неоднократные нарушения правил",
}

#: Страйк «контент снят по жалобам» (А2): ролик, история, сообщение комнаты
#: или комментарий, который порог независимых жалобщиков снял с показа.
#: Тип записи журнала; счёт идёт по category="content" тем же срезом, что у
#: текстовых страйков (text_strike_count).
CONTENT_REMOVED_TYPE = "content_removed"
#: 3 снятых единицы за 90 дней. Порог не ниже: каждая единица — уже 2–3
#: независимых жалобщика, но и не с первой: одну публикацию могут снять
#: сговором или из мести. Окно длиннее текстового (30д): жалобы копятся
#: медленнее автомодерации — зритель должен ещё наткнуться на контент.
CONTENT_STRIKE_LIMIT = 3
CONTENT_STRIKE_WINDOW = timedelta(days=90)
CONTENT_BAN_REASON = "Публикации, снятые по жалобам: неоднократные нарушения правил"


@dataclass
class TextStrikeOutcome:
    """Итог текстового страйка — что случилось и что сказать человеку.

    Не готовый HTTP-ответ, потому что вызывающие разные: REST отвечает
    JSONResponse/HTTPException, WebSocket — send_json + close. Ответ строят
    banned_response() и warning_text() поверх этих полей.
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


def banned_response(user: User, detail: str) -> JSONResponse:
    """Готовый 403 «аккаунт заблокирован» — единственный законный ответ после бана.

    Вызывающий ОБЯЗАН вернуть его как есть: бан пишется в сессию запроса, и
    HTTPException откатил бы его вместе с ответом. Клиент по коду BANNED_CODE
    уводит человека на экран блокировки со сроком и платным разбаном.
    """
    from middleware.auth import BANNED_CODE

    return JSONResponse(
        status_code=403,
        content={
            "detail": detail,
            "code": BANNED_CODE,
            "banned_until": user.banned_until.isoformat() if user.banned_until else None,
        },
    )


async def text_strike_count(user_id: str, category: str, window: timedelta) -> int:
    """Сколько blocked-текстов этой категории набралось за окно.

    Журнал пишется своей сессией (log_moderation) и переживает откат запроса,
    поэтому счёт включает и текущее нарушение — вызывающий пишет журнал ДО
    подсчёта. Окно обрезается последним разбаном (AMNESTY_TYPES): платный или
    админский разбан обнуляет счёт, в новый бан ведут только новые нарушения.
    Сбой журнала — 0: лучше пропустить эскалацию, чем банить по фантому.
    Сессия — из журнального пула, как у identity_strikes: вызов идёт при
    удерживаемой сессии запроса (или ban_session WS-чата — тоже общий пул),
    и вторая сессия из общего пула под залпом — самоблокировка.
    """
    from database.connection import log_session_factory
    from models.models import AiModerationLog

    граница = datetime.now(timezone.utc) - window
    try:
        async with log_session_factory()() as session:
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


async def register_text_strike(
    session: AsyncSession, user: User, verdict: dict
) -> TextStrikeOutcome | None:
    """Посчитать текстовый страйк и забанить, если категория дошла до порога.

    Контракт: вызывается ПОСЛЕ log_moderation с тем же вердиктом — запись
    о текущем нарушении уже в журнале, счёт включает её. None — вердикт safe
    или без правила (категории нет в TEXT_STRIKE_RULES).

    Если outcome.banned — бан записан в сессию запроса, и вызывающий ОБЯЗАН
    ответить без исключения (banned_response для REST, send_json для WS):
    HTTPException откатил бы бан. Обычный отказ (banned=False) можно отдавать
    и исключением — страйк в журнале живёт своей сессией и откат переживёт.
    """
    if not verdict.get("blocked"):
        return None
    category = verdict.get("category") or "text"
    правило = TEXT_STRIKE_RULES.get(category)
    if правило is None:
        return None
    limit, window = правило

    count = await text_strike_count(user.id, category, window)
    if count < limit:
        return TextStrikeOutcome(
            category=category, count=count, limit=limit,
            banned=False, banned_until=None,
        )

    banned = await ban_user_for_violation(
        session, user, TEXT_BAN_REASONS[category], category=category
    )
    # False — админ/владелец: автоматика их не банит, для них это остаётся
    # обычным отказом со счётом
    return TextStrikeOutcome(
        category=category, count=count, limit=limit,
        banned=banned, banned_until=user.banned_until if banned else None,
    )


async def enforce_text_verdict(
    session: AsyncSession, user: User, verdict: dict, detail: str
) -> JSONResponse | None:
    """Единый исход blocked-текста для REST-точек: страйк, потом отказ или бан.

    None — вердикт safe, вызывающий продолжает. Иначе либо возвращает готовый
    403 (порог страйков достигнут, бан уже в сессии запроса — вернуть КАК
    ЕСТЬ), либо бросает прежний 422, дополненный счётом «нарушение N из M».

    Контракт тот же, что у register_text_strike: log_moderation уже вызван
    с этим вердиктом. Для точек с особыми исходами (анкета с автоудалением
    рекламы, WebSocket) — собирать ответ из register_text_strike напрямую.
    """
    from fastapi import HTTPException

    if not verdict.get("blocked"):
        return None
    исход = await register_text_strike(session, user, verdict)
    if исход is not None and исход.banned:
        return banned_response(
            user, f"Аккаунт заблокирован. {TEXT_BAN_REASONS[исход.category]}"
        )
    счёт = f" {исход.warning_text()}" if исход is not None else ""
    raise HTTPException(status_code=422, detail=f"{detail}.{счёт}")


async def register_content_strike(
    session: AsyncSession, author_id: str, метка: str
) -> None:
    """Страйк автору за единицу контента, снятую с показа по жалобам (А2).

    Вызывается из ручки жалобы РОВНО в момент снятия (is_hidden False→True):
    повторные жалобы на уже снятое до ветки не доходят, поэтому одна единица
    контента — один страйк. Жалобщику исход не виден, его ответ остаётся 204:
    банится третье лицо — автор, и узнаёт он из Redis-события и сообщения
    бота (их публикует ban_user_for_violation).

    Забаненному автору страйк не пишется вовсе: пока он отбывает срок, люди
    продолжают натыкаться на его СТАРЫЕ публикации, и каждое снятие двигало
    бы лестницу без нового действия с его стороны.

    Если бан применён, он записан в сессию запроса — вызывающий обязан дойти
    до commit без исключений (все четыре ручки жалоб отвечают 204 сразу).
    """
    result = await session.execute(select(User).where(User.id == author_id))
    автор = result.scalar_one_or_none()
    if автор is None or автор.is_banned:
        return

    from services.ai_moderation import log_moderation

    await log_moderation(
        author_id, CONTENT_REMOVED_TYPE, метка,
        {"blocked": True, "category": "content", "reason": "Снят с показа по жалобам"},
    )
    # Текущее снятие уже в журнале — счёт включает его (контракт как у текстов)
    count = await text_strike_count(author_id, "content", CONTENT_STRIKE_WINDOW)
    if count < CONTENT_STRIKE_LIMIT:
        return
    await ban_user_for_violation(session, автор, CONTENT_BAN_REASON, category="content")


async def register_identity_strike(
    session: AsyncSession, user: User, strike_type: str, content: str, reason: str
) -> JSONResponse | None:
    """Записать страйк «чужое лицо» и забанить, если это уже система.

    Страйк — запись в журнале модерации (тип из IDENTITY_STRIKE_TYPES),
    журнал пишется своей сессией и переживает откат запроса. Набралось
    IDENTITY_STRIKE_LIMIT за окно — аккаунт блокируется: живая съёмка честная
    или гейт фото пройден, а лицо стабильно не то — это подмена личности,
    а не неудачный кадр.

    Возвращает готовый 403-ответ, если бан применён. Вызывающий ОБЯЗАН
    вернуть его как есть: чистый JSONResponse коммитит сессию запроса,
    исключение откатило бы сам бан. None — бана нет, вызывающий отвечает
    обычным отказом (хоть исключением: страйк уже в журнале, он переживёт).
    """
    # Локальный импорт — не от цикла, а от слоёв: ai_moderation сам по себе
    # тяжёлый, а enforcement нужен и в лёгких местах
    from services.ai_moderation import log_moderation

    await log_moderation(
        user.id, strike_type, content, {"blocked": True, "reason": reason}
    )
    if await identity_strikes(user.id) < IDENTITY_STRIKE_LIMIT:
        return None
    if not await ban_user_for_violation(
        session, user,
        "Чужие фото в анкете: лицо владельца несколько раз не совпало с фотографиями",
        category="identity",
    ):
        return None
    return banned_response(
        user, "Аккаунт заблокирован: фотографии в анкете не принадлежат владельцу"
    )


async def ban_user_for_violation(
    session: AsyncSession,
    target: User,
    reason: str,
    *,
    category: str = "manual",
    duration_hours: int | None = None,
) -> bool:
    """Заблокировать пользователя за пойманное нарушение.

    Срок выбирает лестница категории (BAN_LADDERS) по числу прошлых банов;
    ``duration_hours`` — явный срок мимо лестницы, для ручного бана из админки
    (0 или отрицательное значение не имеет смысла и читается как вечный).
    После применения срок лежит в ``target.banned_until`` (None — вечный).

    Возвращает True, если бан применён. Админов и владельцев автоматика не
    трогает (False): ложное срабатывание AI не должно выносить команду —
    их случай разбирает живой владелец.
    """
    if target.role in ("admin", "owner"):
        logger.warning(
            f"Автобан пропущен: пользователь {target.id} имеет роль {target.role} ({reason})"
        )
        return False

    if duration_hours is not None and duration_hours > 0:
        срок: timedelta | None = timedelta(hours=duration_hours)
    else:
        лестница = BAN_LADDERS.get(category, BAN_LADDERS["manual"])
        ступень = min(await prior_ban_count(target.id), len(лестница) - 1)
        срок = лестница[ступень]
    banned_until = datetime.now(timezone.utc) + срок if срок else None

    target.is_banned = True
    target.banned_until = banned_until
    await session.flush()

    # Запись «бан применён» — по ней следующая лестница выберет ступень выше.
    # Пишется своей сессией ДО побочных эффектов: если Redis упадёт, счёт
    # рецидива всё равно должен сойтись.
    from services.ai_moderation import log_moderation

    await log_moderation(
        target.id,
        BAN_APPLIED_TYPE,
        category,
        {"blocked": True, "reason": f"{reason} — {ban_term_text(banned_until)}"},
    )

    # Список забаненных живёт отдельно от пользователя: удаление аккаунта
    # каскадом стирает бан, и забаненный возвращался тем же аккаунтом. Пишем обе
    # привязки — и Telegram, и Apple, — чтобы обход не прошёл ни одним входом
    await remember_ban(
        session,
        telegram_id=target.telegram_id,
        apple_id=target.apple_id,
        reason=reason,
        banned_until=banned_until,
    )

    # Бан должен убивать и уже выданные токены: HTTP-запросы отсекаются
    # проверкой is_banned, но открытый WebSocket её не переспрашивает
    await revoke_all_for_user(target.id)

    # Уведомления — лучшая попытка: бан состоялся и без них
    try:
        from services.realtime import get_redis
        r = await get_redis()
        срок_iso = banned_until.isoformat() if banned_until else None
        await r.publish(
            f"dating:user:{target.id}",
            json.dumps({"type": "banned", "reason": reason, "banned_until": срок_iso}),
        )
        # Боту — отдельным каналом (bot/services/redis_subscriber.py):
        # он шлёт в Telegram сообщение о бане со сроком и кнопкой платной
        # досрочной разблокировки
        await r.publish(
            "dating:bot:events",
            json.dumps({
                "type": "banned",
                "user_id": target.id,
                "reason": reason,
                "banned_until": срок_iso,
            }),
        )
    except Exception:
        pass

    logger.warning(
        f"Автобан: пользователь {target.id} заблокирован {ban_term_text(banned_until)}"
        f" — {reason} (категория {category})"
    )
    return True


async def lift_ban_if_expired(session: AsyncSession, user: User) -> bool:
    """Снять бан, срок которого вышел. True — бан снят, пользователь чист.

    Ленивое истечение вместо фонового джоба: проверяется в get_current_user и
    login-путях, то есть ровно в момент, когда забаненный пытается вернуться.
    Джобу нечего было бы делать раньше этого момента, а сломаться молча он может.

    Журнальную амнистию НЕ пишем: отсиженный срок — не прощение, и следующее
    нарушение обязано получить ступень выше. Сбрасывают лестницу только разбан
    админом (unban_admin); платный разбан не сбрасывает и её.
    """
    срок = _aware(user.banned_until)
    if not user.is_banned or срок is None or срок > datetime.now(timezone.utc):
        return False

    user.is_banned = False
    user.banned_until = None
    # Память банов тоже чистим: без этого удаление аккаунта после отбытого
    # срока воскрешало бы бан при повторной регистрации
    await forgive(session, telegram_id=user.telegram_id, apple_id=user.apple_id)
    await session.flush()
    logger.info(f"Бан истёк и снят при входе: пользователь {user.id}")
    return True
