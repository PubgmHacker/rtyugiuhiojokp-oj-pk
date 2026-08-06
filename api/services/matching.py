from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select, and_, not_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.models import User, Profile, Like, Block, Subscription, Referral
from models.schemas import DeckProfile
from services.public_profile import возраст_из_даты, публичный_возраст
from utils import as_list

settings = get_settings()

#: Насколько платный буст поднимает анкету. Множитель — чтобы эффект не тонул
#: в баллах за интересы, слагаемое — чтобы буст работал и у пустой анкеты.
#: Сколько минут после последней активности считаем «сейчас в сети».
#: Точное время последнего входа не показываем: «был в 14:32» — это слежка,
#: а флаг помогает решить, писать ли сегодня.
ОНЛАЙН_МИНУТ = 10

BOOST_MULTIPLIER = 3.0
BOOST_BONUS = 40.0


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Расстояние между двумя точками в км."""
    if not all([lat1, lon1, lat2, lon2]):
        return 0
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return int(R * c)


def _passes_niche_filters(mine: Profile, other: Profile) -> bool:
    """Проходит ли анкета нишевые фильтры (цель, субкультура, город, рост).

    Правило одно на все фильтры: пустой фильтр пропускает всех, а анкета без
    указанного поля НЕ отсеивается по этому полю. Иначе включённый фильтр
    «гот» прятал бы и тех, кто просто не заполнил графу, и человек решил бы,
    что в приложении никого нет.

    Рост — исключение: если фильтр по росту задан, анкеты без роста
    отсеиваются, потому что «подойдёт ли» тут проверить нечем.
    """
    if mine.filter_goal and other.goal and other.goal != mine.filter_goal:
        return False
    if (
        mine.filter_subculture
        and other.subculture
        and other.subculture != mine.filter_subculture
    ):
        return False
    if mine.filter_city and (other.city or "").strip().lower() != mine.filter_city.strip().lower():
        return False

    if mine.filter_height_min or mine.filter_height_max:
        if other.height_cm is None:
            return False
        if mine.filter_height_min and other.height_cm < mine.filter_height_min:
            return False
        if mine.filter_height_max and other.height_cm > mine.filter_height_max:
            return False

    return True


def _compatibility(
    my_profile: Optional[Profile],
    other: Profile,
    distance: Optional[int],
    my_interests: set,
) -> tuple[Optional[int], Optional[str]]:
    """Процент совместимости и человеческая причина для карточки анкеты.

    Считается локально по тем данным, что уже загружены: общие интересы,
    город, расстояние. Базовые 55% — чтобы у полностью незаполненных анкет
    не выходил обидный ноль; выше 96 не поднимаем, обещать «идеальную пару»
    по трём полям нечестно.

    Без своей анкеты сравнивать не с чем — тогда процент не показываем вовсе,
    это честнее случайного числа.
    """
    if not my_profile:
        return None, None

    other_interests = set(as_list(other.interests))
    shared = my_interests & other_interests
    same_city = bool(
        my_profile.city
        and other.city
        and my_profile.city.strip().lower() == other.city.strip().lower()
    )

    score = 55.0
    score += min(len(shared), 5) * 6
    if same_city:
        score += 8
    if distance is not None and distance <= 30:
        score += 4
    score = max(40.0, min(96.0, score))

    if shared:
        listed = ", ".join(sorted(shared)[:3])
        reason = f"Общие интересы: {listed}"
    elif same_city:
        reason = "Вы в одном городе"
    elif distance is not None and distance <= 30:
        reason = f"Совсем рядом — {distance} км"
    else:
        reason = None

    return int(round(score)), reason


async def _sample_candidates(
    session: AsyncSession,
    exclude_ids: set[str],
    limit: int,
    extra_filters: Optional[list] = None,
) -> list[Profile]:
    """Случайные кандидаты для деки без сортировки всей таблицы.

    `ORDER BY random()` заставляет Postgres присвоить случайное число каждой
    подходящей строке и отсортировать весь набор — индекс тут бесполезен, и
    на десятках тысяч анкет это Seq Scan на каждый запрос деки.

    Вместо этого берём случайную точку на `sample_key` и читаем следующие
    строки по индексу. Ключ упорядочен, поэтому это Index Scan с ранним
    выходом. У конца диапазона строк не хватит, поэтому добираем с начала —
    иначе анкеты с большим ключом систематически видели бы полупустую деку.
    """
    base_filters = [
        User.is_banned == False,
        # Инкогнито и пауза убирают из деки одинаково, но это разные вещи:
        # инкогнито — платная функция Plus, пауза — базовое право уйти
        not_(Profile.is_incognito),
        not_(Profile.is_paused),
        Profile.display_name != "",
        *(extra_filters or []),
    ]
    if exclude_ids:
        base_filters.append(not_(Profile.user_id.in_(exclude_ids)))

    async def _scan(*extra) -> list[Profile]:
        result = await session.execute(
            select(Profile)
            .join(User, Profile.user_id == User.id)
            .where(and_(*base_filters, *extra))
            .order_by(Profile.sample_key)
            .limit(limit)
        )
        return list(result.scalars().all())

    cut = random.random()
    profiles = await _scan(Profile.sample_key >= cut)
    if len(profiles) < limit:
        profiles += await _scan(Profile.sample_key < cut)

    return profiles[:limit]


async def get_deck_profiles(
    session: AsyncSession,
    user_id: str,
    limit: int = 10,
) -> list[DeckProfile]:
    """Получить анкеты для свайп-дека с AI-сортировкой."""
    # Get user's profile for preferences
    result = await session.execute(select(Profile).where(Profile.user_id == user_id))
    my_profile = result.scalar_one_or_none()

    # Get already liked/passed IDs
    result = await session.execute(
        select(Like.liked_id).where(Like.liker_id == user_id)
    )
    liked_ids = {row[0] for row in result.all()}

    # Блокировки действуют в обе стороны: и тот, кого я заблокировал, и тот,
    # кто заблокировал меня, не должны попадать в деку. Иначе жертва
    # харассмента снова увидит обидчика, а он — её.
    result = await session.execute(
        select(Block.blocked_id).where(Block.blocker_id == user_id)
    )
    blocked_ids = {row[0] for row in result.all()}
    result = await session.execute(
        select(Block.blocker_id).where(Block.blocked_id == user_id)
    )
    blocked_ids |= {row[0] for row in result.all()}

    # Кто поставил мне «пропустить» — взаимности с ними уже не будет,
    # показывать их анкеты повторно означает тратить деку впустую
    result = await session.execute(
        select(Like.liker_id).where(
            and_(Like.liked_id == user_id, Like.type == "pass")
        )
    )
    passed_me_ids = {row[0] for row in result.all()}

    # Exclude: self, liked/passed, banned, incognito users.
    # Не отмечаем анкеты «просмотренными» при загрузке — иначе повторный
    # запрос деки (перезагрузка страницы) сжигает непросмотренные анкеты.
    exclude_ids = liked_ids | blocked_ids | passed_me_ids | {user_id}

    profiles = await _sample_candidates(session, exclude_ids, limit * 3)

    # Активные премиумы среди кандидатов — буст в выдаче
    premium_ids: set[str] = set()
    referral_boost_ids: set[str] = set()
    # Кто прямо сейчас под платным бустом. Считаем по времени, а не по флагу:
    # прошедшая дата сама означает «буста нет»
    boosted_ids: set[str] = {
        p.user_id
        for p in profiles
        if p.boost_until and p.boost_until > datetime.now(timezone.utc)
    }
    if profiles:
        candidate_ids = [p.user_id for p in profiles]
        result = await session.execute(
            select(Subscription.user_id).where(and_(
                Subscription.user_id.in_(candidate_ids),
                Subscription.plan != "free",
                or_(
                    Subscription.expires_at.is_(None),
                    Subscription.expires_at > datetime.now(timezone.utc),
                ),
            ))
        )
        premium_ids = {row[0] for row in result.all()}

        # Реферальный буст: пригласил >= N друзей → анкета выше в выдаче
        result = await session.execute(
            select(Referral.referrer_id)
            .where(Referral.referrer_id.in_(candidate_ids))
            .group_by(Referral.referrer_id)
            .having(func.count(Referral.id) >= settings.REFERRAL_MIN_INVITES)
        )
        referral_boost_ids = {row[0] for row in result.all()}

    # «Сейчас в сети» — одним запросом на всю деку: обращаться за этим на
    # каждую карточку значило бы N+1 на самом горячем экране
    недавно = datetime.now(timezone.utc) - timedelta(minutes=ОНЛАЙН_МИНУТ)
    онлайн: set[str] = set()
    if candidate_ids:
        result = await session.execute(
            select(User.id).where(and_(
                User.id.in_(candidate_ids),
                User.last_seen_at.is_not(None),
                User.last_seen_at >= недавно,
            ))
        )
        онлайн = {row[0] for row in result.all()}

    # Filter by preferences and build deck
    deck: list[DeckProfile] = []
    my_age = возраст_из_даты(my_profile.birth_date) if my_profile else None
    my_interests_pre = set(as_list(my_profile.interests)) if my_profile else set()

    for profile in profiles:
        # Gender preference filter
        if my_profile and my_profile.looking_for != "any":
            if profile.gender != my_profile.looking_for and profile.gender != "other":
                continue

        # Age preference filter
        profile_age = возраст_из_даты(profile.birth_date)
        if my_profile and my_age and profile_age:
            if profile_age < my_profile.age_min or profile_age > my_profile.age_max:
                continue
        if my_profile and my_age:
            if my_age < profile.age_min or my_age > profile.age_max:
                continue

        # Looking for filter (reverse)
        if profile.looking_for != "any" and my_profile:
            if profile.looking_for != my_profile.gender and my_profile.gender != "other":
                continue

        # Нишевые фильтры. Каждый включается только если человек его задал:
        # незаполненный фильтр не должен сужать выдачу, иначе новичок с пустой
        # анкетой не увидел бы никого.
        if my_profile and not _passes_niche_filters(my_profile, profile):
            continue

        # Расстояние. Осознанное решение, а не побочный эффект отсутствия
        # координат: без геопозиции километры посчитать не из чего, поэтому
        # фильтр по расстоянию — это ЧАСТИЧНЫЙ фильтр, а не полный, как
        # у роста. Кандидат без координат не исключается фильтром
        # `distance_max` (тот же принцип, что и в `_passes_niche_filters`:
        # незаполненное поле не наказывает анкету). Симметрично: если
        # координат нет у МЕНЯ, `distance_max` вообще не проверяется ни для
        # кого — это не баг, а следствие того же принципа, но веб уже
        # предупреждает об этом в фильтрах (Discover.tsx), чтобы ползунок не
        # выглядел рабочим, когда он не работает.
        distance = None
        if (my_profile and my_profile.latitude and my_profile.longitude
                and profile.latitude and profile.longitude):
            distance = _haversine(
                my_profile.latitude, my_profile.longitude,
                profile.latitude, profile.longitude,
            )
            if my_profile.distance_max and distance > my_profile.distance_max:
                continue

        # Совместимость считаем на месте, без обращения к модели: дека — это
        # десятки анкет на каждый запрос, и LLM-скоринг каждой из них стоил бы
        # секунд ожидания и денег. Полный AI-разбор остаётся на момент мэтча,
        # где он один и уместен (services/ai_matchmaker.py: score_match).
        compat_score, compat_reason = _compatibility(
            my_profile, profile, distance, my_interests_pre,
        )

        # Возраст и расстояние прячем в карточке, но подбор по ним оставляем:
        # выпади анкета из фильтров, человек просто перестал бы её видеть
        deck.append(DeckProfile(
            id=profile.user_id,
            display_name=profile.display_name or "",
            age=публичный_возраст(profile),
            city=profile.city or "",
            bio=profile.bio or "",
            photos=as_list(profile.photos),
            interests=as_list(profile.interests),
            ai_bio=profile.ai_bio,
            distance=None if profile.hide_distance else distance,
            match_score=compat_score,
            match_reason=compat_reason,
            goal=profile.goal or "",
            subculture=profile.subculture or "",
            mbti=profile.mbti or "",
            height_cm=profile.height_cm,
            # Инкогнито и пауза уже отсеяны выборкой, но флаг всё равно
            # считаем от них: если фильтр однажды ослабнет, «в сети» не должно
            # выдать спрятавшегося
            is_online=(
                profile.user_id in онлайн
                and not profile.is_incognito
                and not profile.is_paused
            ),
        ))

    # Умная сортировка вместо рандома: общие интересы, город, близость,
    # премиум-буст + лёгкий шум, чтобы дека не была детерминированной
    my_interests = set(as_list(my_profile.interests)) if my_profile else set()
    my_city = (my_profile.city or "").strip().lower() if my_profile else ""

    referral_mult = 1 + settings.REFERRAL_BOOST_PERCENT / 100

    def _rank(p: DeckProfile) -> float:
        score = 0.0
        score += len(my_interests & set(p.interests)) * 10
        if my_city and (p.city or "").strip().lower() == my_city:
            score += 15
        if p.distance is not None:
            score += max(0.0, 20 - p.distance / 5)
        if p.id in premium_ids:
            score += 25
        if p.id in referral_boost_ids:
            score *= referral_mult  # пригласил друзей — анкета выше
        if p.id in boosted_ids:
            # Платный буст сильнее прочих слагаемых, иначе покупка не заметна.
            # Множитель, а не константа: иначе он терялся бы у анкет, которые
            # и без него набрали много по интересам и близости.
            score = score * BOOST_MULTIPLIER + BOOST_BONUS
        return score + random.uniform(0, 8)

    deck.sort(key=_rank, reverse=True)
    return deck[:limit]
