"""Личка без взаимного мэтча — платный крючок (аналог «Мимолёта»).

Топовый тариф может написать человеку, который его ещё не лайкал. Это
`Match` с `kind="direct"`: беседа и её сообщения идут через тот же чат, что
и обычный мэтч (`routers/chat.py`, `services/chat_delivery.py`) — только с
одним отличием, встроенным в общий путь отправки: до ответа получателя
(`direct_answered=False`) отправитель может отправить РОВНО ОДНО сообщение.

Гонка та же, что у суперлайков и кейсов: два параллельных запроса читают
«писем сегодня: 2 из 3» одновременно и оба проходят. Лечится тем же приёмом —
`pg_advisory_xact_lock` на пользователя, взятый ДО подсчёта использованного.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import NamedTuple, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Block, Match, Profile
from services.plans import (
    FEATURE_MIN_TIER,
    TIERS,
    direct_messages_per_day,
    tier_allows,
)
from services.premium import current_tier


class DirectDenied(NamedTuple):
    """Причина отказа — код для клиента и человеческое сообщение."""

    code: str
    detail: str


#: Причины по кодам — коду важно быть стабильным (клиент решает по нему,
#: показывать ли «повысьте тариф» или просто текст ошибки), а текст можно
#: менять свободно.
DENIED_SELF = DirectDenied("self", "Нельзя написать самому себе")
DENIED_NOT_FOUND = DirectDenied("not_found", "Анкета не найдена")
DENIED_BLOCKED = DirectDenied("blocked", "Написать нельзя")
DENIED_PAUSED = DirectDenied("unavailable", "Анкета сейчас не принимает сообщения")
DENIED_ALREADY_MATCH = DirectDenied("already_match", "У вас уже есть чат с этим человеком")
#: Имя уровня подставляем из тарифной линейки, а не вписываем словом: при
#: переносе фичи на другой уровень (так уже было — она переехала с Plus на
#: Aurora) текст молча остался бы врать.
DENIED_TIER = DirectDenied(
    "tier",
    "Написать без взаимного лайка можно на "
    f"{TIERS[FEATURE_MIN_TIER['direct_messages']].name}",
)
DENIED_LIMIT = DirectDenied("limit", "Письма без взаимности на сегодня закончились")
DENIED_ONE_BEFORE_REPLY = DirectDenied(
    "awaiting_reply", "Вы уже написали — дождитесь ответа"
)
#: Письмо было и его закрыли, не ответив. Второй заход — это и есть спам, от
#: которого защищает «одно письмо до ответа»: без этого отказа правило обходилось
#: за два запроса — размэтч (его может позвать и сам отправитель) обнулял чат, а
#: следующее письмо заводилось в ту же строку как новое.
DENIED_CLOSED = DirectDenied(
    "closed", "Переписку закрыли — написать снова нельзя"
)


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


async def _direct_sent_today(session: AsyncSession, sender_id: str) -> int:
    """Сколько писем этот человек отправил за сутки.

    Считает по `initiator_id`, а НЕ по `kind == "direct"`. Разница видна ровно
    в одном месте, зато дорогом: взаимный лайк поверх беседы-письма переводит
    её в `kind="match"` (`routers/likes.py`), и фильтр по типу вернул бы
    отправителю потраченное письмо обратно. Обычные мэтчи в подсчёт не лезут
    сами собой — у них `initiator_id` пуст.
    """
    since = datetime.now(timezone.utc) - timedelta(days=1)
    result = await session.execute(
        select(func.count(Match.id)).where(and_(
            Match.initiator_id == sender_id,
            Match.created_at >= since,
        ))
    )
    return result.scalar() or 0


async def direct_quota_left(session: AsyncSession, sender_id: str) -> int:
    """Сколько писем без взаимности осталось сегодня — для витрины на клиенте."""
    tier = await current_tier(session, sender_id)
    if not tier_allows(tier, "direct_messages"):
        return 0
    per_day = direct_messages_per_day(tier)
    used = await _direct_sent_today(session, sender_id)
    return max(0, per_day - used)


async def find_match(session: AsyncSession, a: str, b: str) -> Optional[Match]:
    u1, u2 = _pair(a, b)
    result = await session.execute(
        select(Match).where(and_(Match.user1_id == u1, Match.user2_id == u2))
    )
    return result.scalar_one_or_none()


async def can_start_direct(
    session: AsyncSession, sender_id: str, recipient_id: str,
) -> Optional[DirectDenied]:
    """Можно ли ЗАВЕСТИ новую беседу-письмо без взаимного лайка.

    None — можно. Не берёт advisory-lock: та часть, что вправду подвержена
    гонке (суточный лимит), проверяется отдельно внутри лока в
    `start_direct_message`. Эта функция — быстрые, не гоночные отказы:
    тариф, блок, пауза, уже существующий match.
    """
    if sender_id == recipient_id:
        return DENIED_SELF

    result = await session.execute(
        select(Block.id).where(or_(
            and_(Block.blocker_id == sender_id, Block.blocked_id == recipient_id),
            and_(Block.blocker_id == recipient_id, Block.blocked_id == sender_id),
        ))
    )
    if result.scalar_one_or_none():
        return DENIED_BLOCKED

    result = await session.execute(
        select(Profile).where(Profile.user_id == recipient_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return DENIED_NOT_FOUND
    if profile.is_paused or profile.is_incognito:
        return DENIED_PAUSED

    existing = await find_match(session, sender_id, recipient_id)
    if existing and existing.is_active and existing.kind == "match":
        return DENIED_ALREADY_MATCH

    tier = await current_tier(session, sender_id)
    if not tier_allows(tier, "direct_messages"):
        return DENIED_TIER

    return None


async def start_direct_message(
    session: AsyncSession, sender_id: str, recipient_id: str,
) -> Match | DirectDenied:
    """Завести (или переиспользовать) беседу-письмо и списать суточный лимит.

    Возвращает готовый `Match`, ЕЩЁ БЕЗ первого сообщения — его пишет вызывающий
    роутер через `services/chat_delivery.save_message`/`fan_out`, как и обычный
    чат. Здесь только создание переписки и учёт лимита писем — застолблённых
    под advisory-локами `dating:likes:{sender_id}` и `dating:pair:{u1}:{u2}`,
    чтобы два параллельных запроса не отправили два письма сверх суточной нормы
    и не создали строку пары одновременно со встречным лайком.
    """
    denied = await can_start_direct(session, sender_id, recipient_id)
    if denied:
        return denied

    # Два лока, в том же порядке, что и в `routers/likes.py`: сначала личный
    # (суточный лимит писем — личный и считается по всем адресатам сразу),
    # потом парный.
    #
    # Парный обязателен, хотя лимит личный: строку `Match` для этой пары заводит
    # и встречный лайк. Без общего с ним ключа письмо и лайк создавали бы её
    # одновременно — второй падал бы на `uq_match_pair` пятисоткой, причём
    # именно в тот момент, когда пара сошлась.
    #
    # Порядок захвата един для обоих путей и менять его нельзя: разный порядок
    # — это дедлок между письмом и встречным лайком.
    await session.execute(
        sa_text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"dating:likes:{sender_id}"},
    )
    u1, u2 = _pair(sender_id, recipient_id)
    await session.execute(
        sa_text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"dating:pair:{u1}:{u2}"},
    )
    # Повторная проверка внутри лока: до захвата лока могла проскочить другая
    # беседа с тем же получателем в параллельном запросе
    existing = await find_match(session, sender_id, recipient_id)
    if existing and existing.is_active and existing.kind == "match":
        return DENIED_ALREADY_MATCH
    if existing and existing.is_active and existing.kind == "direct":
        # Уже есть письмо этой паре — не плодим вторую беседу, используем её.
        # Лимит второй раз не списываем: это не новое письмо, а продолжение
        # того же самого
        return existing
    if (
        existing
        and not existing.is_active
        and existing.kind == "direct"
        and existing.initiator_id == sender_id
        and not existing.direct_answered
    ):
        # Письмо было, ответа не было, беседу закрыли. Реактивировать её как
        # новое письмо значит обойти «одно письмо до ответа» в два запроса:
        # `unmatch` доступен обеим сторонам, и отправитель мог позвать его сам.
        # Закрытая без ответа переписка — это и есть ответ.
        return DENIED_CLOSED

    tier = await current_tier(session, sender_id)
    per_day = direct_messages_per_day(tier)
    used = await _direct_sent_today(session, sender_id)
    if used >= per_day:
        return DENIED_LIMIT

    if existing:
        # Была неактивная (например, размэтч) — реактивируем как direct,
        # а не плодим вторую строку: unique constraint на (user1_id, user2_id)
        existing.is_active = True
        existing.kind = "direct"
        existing.initiator_id = sender_id
        existing.direct_answered = False
        # Новый раунд — письмо этого раунда ещё не отправлено. Без сброса
        # старый флаг отказал бы отправителю в первом же письме
        existing.direct_letter_sent = False
        # `created_at` — не «когда пара познакомилась», а «когда списано
        # письмо»: по нему считает `_direct_sent_today`. Со старой датой
        # реактивированная беседа выпадала из суточного окна, и суточный лимит
        # обходился размэтчем — тем же приёмом, что и правило одного письма
        existing.created_at = datetime.now(timezone.utc)
        match = existing
    else:
        match = Match(
            user1_id=u1, user2_id=u2,
            kind="direct", initiator_id=sender_id, direct_answered=False,
            direct_letter_sent=False, is_active=True,
        )
        session.add(match)
    await session.flush()
    return match


async def can_send_message(
    session: AsyncSession, match: Match, sender_id: str,
) -> Optional[DirectDenied]:
    """Можно ли отправить СЛЕДУЮЩЕЕ сообщение в уже существующей беседе.

    Живёт в общем пути отправки (`chat_delivery.save_message`), а не в отдельной
    ветке чата: обычный `match` пропускает без проверок, `direct` — только если
    отвечает получатель или отправитель ещё ни разу не писал.

    «Письмо уже было» — это флаг раунда `direct_letter_sent`, а не факт
    существования беседы и не COUNT по её сообщениям. Оба «очевидных» варианта
    уже пробовались и оба неверны. «Беседа есть — значит письмо ушло» нельзя
    поставить на общий путь отправки: правило запретило бы и первое письмо, а
    `POST /matches/direct` обходил его целиком — `start_direct_message`
    возвращал существующую беседу, и роутер писал в неё без единой проверки.
    COUNT по сообщениям ломается на второй итерации: строка `Match` у пары одна
    и переиспользуется, поэтому сообщения давно закрытой переписки лежат в ней
    же и отказывают отправителю в первом письме нового раунда.
    """
    if match.kind != "direct":
        return None
    if match.direct_answered:
        return None
    if match.direct_letter_sent and sender_id == match.initiator_id:
        return DENIED_ONE_BEFORE_REPLY
    return None


async def mark_answered_if_needed(match: Match, sender_id: str) -> None:
    """Отметить в беседе факт этого сообщения — зовётся при каждом сохранении.

    Два флага одного раунда: письмо инициатора закрывает ему право писать
    дальше, ответ получателя снимает ограничение совсем. Ставятся здесь, в
    одном месте и в одной транзакции с записью сообщения (`save_message`), —
    разъехаться с фактом сообщения они не должны ни на одном из путей
    отправки, а их четыре.

    Не коммитит сама: коммит делает `save_message` вместе со вставкой.
    """
    if match.kind != "direct" or match.direct_answered:
        return
    if sender_id == match.initiator_id:
        match.direct_letter_sent = True
    else:
        match.direct_answered = True
