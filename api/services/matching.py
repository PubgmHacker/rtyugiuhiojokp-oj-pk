from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, and_, not_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.models import User, Profile, Like, Block, Subscription, Referral
from models.schemas import DeckProfile
from services.plans import deck_priority, tier_from_plan
from services.public_profile import буст_активен, возраст_из_даты, публичный_возраст
from services.stickers import картинка_наклейки
from services.decor import безопасный_код
from utils import as_list, официальный, public_photos, public_videos

settings = get_settings()

#: Насколько платный буст поднимает анкету. Множитель — чтобы эффект не тонул
#: в баллах за интересы, слагаемое — чтобы буст работал и у пустой анкеты.
#: Сколько минут после последней активности считаем «сейчас в сети».
#: Точное время последнего входа не показываем: «был в 14:32» — это слежка,
#: а флаг помогает решить, писать ли сегодня.
ОНЛАЙН_МИНУТ = 10

BOOST_MULTIPLIER = 3.0
BOOST_BONUS = 40.0

#: Буст новичка (PRD §2.4.5): первые 24 часа анкета выше в выдаче — цель
#: довести нового человека до первого мэтча в первую же сессию, это
#: сильнейший предиктор возврата на день 2. Множитель угасает линейно от
#: ×1.8 до ×1.0 и считается от User.created_at на лету: в базу ничего не
#: пишется, поэтому нечему рассинхронизироваться и нечего чистить по
#: истечении. Бонус нужен из-за нулевой базы нашего скоринга: у новичка без
#: общих интересов и координат множитель умножал бы ноль. 15 — сила сигнала
#: «один город»: свежесть весит как землячество, но платный буст (×3 + 40)
#: остаётся заметно сильнее.
СВЕЖЕСТЬ_ЧАСОВ = 24.0
СВЕЖЕСТЬ_МНОЖИТЕЛЬ = 0.8
СВЕЖЕСТЬ_БОНУС = 15.0

#: Авторасширение тонкой деки: жёсткий обрыв на радиусе `distance_max`
#: оставлял человека в малом городе с пустой декой — самая дорогая утечка
#: первого дня, бьёт и по удержанию, и по монетизации. Кандидата дальше
#: своего радиуса, но ближе ×3 от него («соседний город») не выбрасываем,
#: а откладываем: он попадёт в выдачу, только если своих не хватило на
#: страницу. Свои всегда выше — соседи идут хвостом, дистанция на карточке
#: честная. Дальше ×3 — уже не сосед, отсекается как раньше.
РАДИУС_СОСЕДЕЙ = 3.0


def _свежесть(created_at: Optional[datetime]) -> float:
    """Доля новичкового буста 0..1: единица в момент регистрации, ноль через сутки."""
    if created_at is None:
        return 0.0
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    часы = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
    return max(0.0, 1.0 - часы / СВЕЖЕСТЬ_ЧАСОВ)


def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """Расстояние между двумя точками в км."""
    if any(value is None for value in (lat1, lon1, lat2, lon2)):
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
    # Тип связи («с кем») — та же безопасная схема, что у цели и субкультуры:
    # пустой фильтр не сужает, а анкета без указанного типа не отсеивается.
    # Жёсткий фильтр по этому полю в маленьком городе мог бы опустошить деку —
    # ровно то, чего мы избегаем и в MBTI (см. profileOptions.ts).
    if (
        mine.filter_relation_type
        and other.relation_type
        and other.relation_type != mine.filter_relation_type
    ):
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

    # Совпадающий тип связи — небольшой бонус, а не решающий фактор: это
    # не менее важно, чем интересы. Одинаковое значение цели и типа связи не
    # складываются в отдельный "идеальный" балл — просто ещё одна точка совпадения.
    same_relation_type = bool(
        getattr(my_profile, "relation_type", "")
        and getattr(other, "relation_type", "")
        and my_profile.relation_type == other.relation_type
    )

    score = 55.0
    score += min(len(shared), 5) * 6
    if same_city:
        score += 8
    if distance is not None and distance <= 30:
        score += 4
    if same_relation_type:
        score += 5
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


def _уже_показывали(user_id: str) -> list:
    """Условия «этого кандидата показывать не надо» — как анти-джойны в SQL.

    Раньше все четыре списка вычитывались в Python и уезжали обратно в запрос
    одним `NOT IN (...)`. У активного свайпера это десятки тысяч id: Postgres
    получал `NOT IN` с 50 000 плейсхолдеров, план не кэшировался (набор
    параметров каждый раз новый), а анти-джойн вырождался в Seq Scan по
    `dating_profiles`. Одно только планирование уходило в секунды.

    `NOT EXISTS` оставляет решение Postgres: он берёт `ix_like_liker`,
    `ix_block_blocker`, `ix_block_blocked`, `ix_like_liked` и делает
    anti-join по индексу, ничего не пересылая через Python.
    """
    return [
        # Кому я уже поставил лайк или «пропустить»
        not_(
            select(Like.id)
            .where(and_(Like.liker_id == user_id, Like.liked_id == Profile.user_id))
            .exists()
        ),
        # Блокировки действуют в обе стороны: и тот, кого я заблокировал, и тот,
        # кто заблокировал меня, не должны попадать в деку. Иначе жертва
        # харассмента снова увидит обидчика, а он — её.
        not_(
            select(Block.id)
            .where(
                or_(
                    and_(
                        Block.blocker_id == user_id,
                        Block.blocked_id == Profile.user_id,
                    ),
                    and_(
                        Block.blocked_id == user_id,
                        Block.blocker_id == Profile.user_id,
                    ),
                )
            )
            .exists()
        ),
        # Кто поставил мне «пропустить» — взаимности с ними уже не будет,
        # показывать их анкеты повторно означает тратить деку впустую
        not_(
            select(Like.id)
            .where(
                and_(
                    Like.liked_id == user_id,
                    Like.liker_id == Profile.user_id,
                    Like.type == "pass",
                )
            )
            .exists()
        ),
        # Сам себя в деке видеть не должен
        Profile.user_id != user_id,
    ]


async def _sample_candidates(
    session: AsyncSession,
    user_id: Optional[str],
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
    if user_id:
        base_filters += _уже_показывали(user_id)

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

    # Кого не показывать (свои лайки и пропуски, блокировки в обе стороны, те,
    # кто пропустил меня, сам пользователь) — решается внутри запроса,
    # анти-джойнами по индексам. Вычитывать эти id в Python нельзя: у активного
    # свайпера их десятки тысяч, и `NOT IN` с таким списком убивает план.
    # Не отмечаем анкеты «просмотренными» при загрузке — иначе повторный
    # запрос деки (перезагрузка страницы) сжигает непросмотренные анкеты.
    profiles = await _sample_candidates(
        session,
        user_id,
        limit * 3,
        # «Только подтверждённые» — единственный нишевый фильтр, который
        # применяется в SQL, а не в `_passes_niche_filters`. Причина не в
        # красоте: остальные фильтры отсеивают единицы, а этот — подавляющее
        # большинство анкет. Отбрасывай его в Python, и выборка из limit*3
        # кандидатов оставляла бы после фильтра две карточки вместо десяти —
        # человек с включённым фильтром видел бы почти пустую деку и решил,
        # что подтверждённых нет вовсе. В запросе `User` уже приджойнен,
        # так что условие ничего не стоит.
        extra_filters=[User.is_verified == True]
        if my_profile is not None and my_profile.filter_verified
        else None,
    )

    # Сколько очков ранжирования даёт уровень подписки каждого кандидата.
    # Пусто — приоритета нет ни у кого (бесплатные и без подписки сюда не
    # попадают вовсе)
    приоритет_по_id: dict[str, int] = {}
    referral_boost_ids: set[str] = set()
    # Кто прямо сейчас под платным бустом. Считаем по времени, а не по флагу:
    # прошедшая дата сама означает «буста нет»
    boosted_ids: set[str] = {
        p.user_id
        for p in profiles
        if буст_активен(p.boost_until)
    }
    # Список кандидатов нужен и ниже (онлайн-статус), поэтому объявляем его
    # до ветки: внутри `if profiles` он оставался неопределённым на пустой
    # деке и главный экран падал с UnboundLocalError
    candidate_ids = [p.user_id for p in profiles]

    if profiles:
        # Читаем именно УРОВЕНЬ, а не факт подписки: приоритет в выдаче
        # продаётся с Ultra, а «максимальный» — только на Aurora (см.
        # plans.DECK_PRIORITY). Пока здесь стояло `plan != "free"`, все
        # платные получали одинаковую прибавку: Plus — незаслуженно, Aurora —
        # ровно столько же, сколько вдвое более дешёвый Ultra.
        result = await session.execute(
            select(Subscription.user_id, Subscription.plan).where(and_(
                Subscription.user_id.in_(candidate_ids),
                or_(
                    Subscription.expires_at.is_(None),
                    Subscription.expires_at > datetime.now(timezone.utc),
                ),
            ))
        )
        приоритет_по_id = {
            user_id: deck_priority(tier_from_plan(plan))
            for user_id, plan in result.all()
        }

        # Реферальный буст: пригласил >= N друзей → анкета выше в выдаче
        result = await session.execute(
            select(Referral.referrer_id)
            .where(Referral.referrer_id.in_(candidate_ids))
            .group_by(Referral.referrer_id)
            .having(func.count(Referral.id) >= settings.REFERRAL_MIN_INVITES)
        )
        referral_boost_ids = {row[0] for row in result.all()}

    # Галочка — одним запросом на всю деку: обращаться за этим на каждую
    # карточку значило бы N+1 на самом горячем экране
    верифицированные: set[str] = set()
    # Бейдж команды — из той же строки, что галочка
    команда: set[str] = set()
    # Буст новичка: доля свежести 0..1 по каждому кандидату моложе суток.
    # Едет тем же запросом, что галочка, — не N+1
    свежесть_по_id: dict[str, float] = {}
    if candidate_ids:
        result = await session.execute(
            select(User.id, User.is_verified, User.role, User.created_at)
            .where(User.id.in_(candidate_ids))
        )
        for uid, is_verified, role, created_at in result.all():
            if is_verified:
                верифицированные.add(uid)
            if официальный(role):
                команда.add(uid)
            доля = _свежесть(created_at)
            if доля > 0:
                свежесть_по_id[uid] = доля

    # Filter by preferences and build deck
    deck: list[DeckProfile] = []
    # Соседние города: кандидаты за радиусом distance_max, но не дальше ×3.
    # В деку не входят, пока своих хватает, — только добирают тонкую
    соседи: list[DeckProfile] = []
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
        за_радиусом = False
        if (
            my_profile
            and my_profile.latitude is not None
            and my_profile.longitude is not None
            and profile.latitude is not None
            and profile.longitude is not None
        ):
            distance = _haversine(
                my_profile.latitude, my_profile.longitude,
                profile.latitude, profile.longitude,
            )
            if my_profile.distance_max and distance > my_profile.distance_max:
                # Авторасширение тонкой деки: сосед не выбрасывается, а
                # откладывается — попадёт в выдачу, только если своих
                # меньше страницы. Дистанция на карточке остаётся честной:
                # человек видит «120 км» и сам решает. Ослабляется ТОЛЬКО
                # радиус — пол, возраст, ниши и блокировки уже отсеяли
                # кандидата выше, соседство их не обходит (гейт PRD §2.6).
                if distance > my_profile.distance_max * РАДИУС_СОСЕДЕЙ:
                    continue
                за_радиусом = True

        # Совместимость считаем на месте, без обращения к модели: дека — это
        # десятки анкет на каждый запрос, и LLM-скоринг каждой из них стоил бы
        # секунд ожидания и денег. Полный AI-разбор остаётся на момент мэтча,
        # где он один и уместен (services/ai_matchmaker.py: score_match).
        compat_score, compat_reason = _compatibility(
            my_profile, profile, distance, my_interests_pre,
        )

        # Возраст и расстояние прячем в карточке, но подбор по ним оставляем:
        # выпади анкета из фильтров, человек просто перестал бы её видеть
        (соседи if за_радиусом else deck).append(DeckProfile(
            id=profile.user_id,
            display_name=profile.display_name or "",
            age=публичный_возраст(profile),
            city=profile.city or "",
            bio=profile.bio or "",
            photos=public_photos(profile.photos),
            videos=public_videos(profile.videos),
            interests=as_list(profile.interests),
            ai_bio=profile.ai_bio,
            distance=None if profile.hide_distance else distance,
            match_score=compat_score,
            match_reason=compat_reason,
            goal=profile.goal or "",
            relation_type=profile.relation_type or "",
            subculture=profile.subculture or "",
            mbti=profile.mbti or "",
            height_cm=profile.height_cm,
            # Инкогнито и пауза уже отсеяны выборкой, но флаг всё равно
            # считаем от них: если фильтр однажды ослабнет, «в сети» не должно
            # выдать спрятавшегося
            sticker=картинка_наклейки(profile.sticker),
            decor=безопасный_код(profile.decor),
            # Незнакомцу не говорим, в сети ли человек: по этому флагу можно
            # следить за чужим расписанием, не будучи даже в мэтче. «В сети»
            # остаётся только внутри мэтча (routers/matches.py) — там оба уже
            # согласились общаться. Поле в схеме живёт ради совместимости
            is_online=False,
            is_verified=(profile.user_id in верифицированные),
            is_official=(profile.user_id in команда),
        ))

    # Умная сортировка вместо рандома: общие интересы, город, близость,
    # премиум-буст + лёгкий шум, чтобы дека не была детерминированной
    my_interests = set(as_list(my_profile.interests)) if my_profile else set()
    my_city = (my_profile.city or "").strip().lower() if my_profile else ""
    my_relation_type = my_profile.relation_type if my_profile else ""
    profiles_with_photos = {
        profile.user_id for profile in profiles if as_list(profile.photos)
    }

    referral_mult = 1 + settings.REFERRAL_BOOST_PERCENT / 100

    def _rank(p: DeckProfile) -> float:
        score = 0.0
        score += len(my_interests & set(p.interests)) * 10
        if my_city and (p.city or "").strip().lower() == my_city:
            score += 15
        if my_relation_type and p.relation_type == my_relation_type:
            score += 5
        if p.distance is not None:
            score += max(0.0, 20 - p.distance / 5)
        score += приоритет_по_id.get(p.id, 0)
        if p.id in referral_boost_ids:
            score *= referral_mult  # пригласил друзей — анкета выше
        доля = свежесть_по_id.get(p.id, 0.0)
        # Наличие фото — внутренний сигнал полноты анкеты. В ответ чужому
        # клиенту Telegram file_id фильтруется из `p.photos`, но такая анкета
        # всё равно не должна терять новичковый буст (бот умеет отдать это
        # фото через Telegram).
        if доля and p.id in profiles_with_photos:
            # Буст новичка: свежая анкета выше — но только с фото, механика
            # не имеет права разгонять пустышки (PRD §2.4.5). Стоит ДО
            # платного буста, чтобы купленный буст оставался сильнее любого
            # бесплатного сигнала
            score = score * (1 + СВЕЖЕСТЬ_МНОЖИТЕЛЬ * доля) + СВЕЖЕСТЬ_БОНУС * доля
        if p.id in boosted_ids:
            # Платный буст сильнее прочих слагаемых, иначе покупка не заметна.
            # Множитель, а не константа: иначе он терялся бы у анкет, которые
            # и без него набрали много по интересам и близости.
            score = score * BOOST_MULTIPLIER + BOOST_BONUS
        return score + random.uniform(0, 8)

    deck.sort(key=_rank, reverse=True)
    if len(deck) < limit and соседи:
        # Тонкая дека: своих меньше страницы — добираем соседними городами,
        # тоже по рангу. Хвостом, а не вперемешку: свой радиус всегда выше
        соседи.sort(key=_rank, reverse=True)
        deck += соседи[: limit - len(deck)]
    return deck[:limit]
