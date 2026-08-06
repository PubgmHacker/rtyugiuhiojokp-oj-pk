from __future__ import annotations

import json
import logging
import random
from datetime import datetime

from sqlalchemy import select, text, func, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL
from services.plans import tier_rank
from database.models import (
    Base,
    Block,
    User,
    Profile,
    Like,
    Match,
    ProcessedPayment,
    Referral,
    Report,
    Subscription,
)

logger = logging.getLogger(__name__)

engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory: async_sessionmaker[AsyncSession] | None = None


def _session_cls() -> async_sessionmaker[AsyncSession]:
    global async_session_factory
    if async_session_factory is None:
        async_session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False,
        )
    return async_session_factory


async def init_db():
    """Create tables if they don't exist."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured")


# ════════════════════════════════════════════════════════════════
#  USER CRUD
# ════════════════════════════════════════════════════════════════

async def get_or_create_user(telegram_id: int, username: str = "", name: str = "") -> dict:
    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()

            if user:
                user.last_seen_at = datetime.now()
                await session.flush()
                return _user_to_dict(user)

            user = User(telegram_id=telegram_id, role="user")
            session.add(user)
            await session.flush()

            # Create empty profile
            profile = Profile(user_id=user.id, display_name=name)
            session.add(profile)
            await session.flush()

            logger.info(f"New user registered: {telegram_id} @{username}")
            return _user_to_dict(user)


async def get_user_by_id(user_id: str) -> dict | None:
    cls = _session_cls()
    async with cls() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        return _user_to_dict(user) if user else None


async def get_profile(user_id: str) -> dict | None:
    cls = _session_cls()
    async with cls() as session:
        result = await session.execute(
            select(Profile).where(Profile.user_id == user_id)
        )
        profile = result.scalar_one_or_none()
        return _profile_to_dict(profile) if profile else None


async def update_profile(user_id: str, **fields) -> dict | None:
    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            result = await session.execute(
                select(Profile).where(Profile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()

            if not profile:
                profile = Profile(user_id=user_id)
                session.add(profile)

            # photos/interests — JSON-колонки, храним списки нативно
            for k, v in fields.items():
                setattr(profile, k, v)

            await session.flush()
            return _profile_to_dict(profile)


async def set_profile_ready(user_id: str) -> None:
    """Mark profile as complete after onboarding."""
    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = result.scalar_one_or_none()
            if user:
                user.is_verified = True


# ════════════════════════════════════════════════════════════════
#  REFERRALS
# ════════════════════════════════════════════════════════════════

async def record_referral(referrer_id: str, invited_id: str) -> dict:
    """Засчитать приглашение. Возвращает {'counted': bool, 'total': int}.

    Защита от накрутки: нельзя пригласить себя, каждый приглашённый
    считается один раз, засчитываются только свежесозданные аккаунты
    (клик по ссылке существующим пользователем не считается).
    """
    from datetime import timedelta

    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            counted = False
            if referrer_id != invited_id:
                result = await session.execute(
                    select(Referral).where(Referral.invited_id == invited_id)
                )
                already = result.scalar_one_or_none()

                result = await session.execute(
                    select(User).where(User.id == invited_id)
                )
                invited = result.scalar_one_or_none()
                is_fresh = bool(
                    invited and invited.created_at
                    and invited.created_at.replace(tzinfo=None)
                    > datetime.utcnow() - timedelta(minutes=5)
                )

                result = await session.execute(
                    select(User).where(User.id == referrer_id)
                )
                referrer_exists = result.scalar_one_or_none() is not None

                if not already and is_fresh and referrer_exists:
                    session.add(Referral(referrer_id=referrer_id, invited_id=invited_id))
                    await session.flush()
                    counted = True

            result = await session.execute(
                select(func.count(Referral.id)).where(Referral.referrer_id == referrer_id)
            )
            total = result.scalar() or 0
            return {"counted": counted, "total": total}


async def get_referral_count(user_id: str) -> int:
    cls = _session_cls()
    async with cls() as session:
        result = await session.execute(
            select(func.count(Referral.id)).where(Referral.referrer_id == user_id)
        )
        return result.scalar() or 0


# ════════════════════════════════════════════════════════════════
#  ПАУЗА И УДАЛЕНИЕ АККАУНТА
# ════════════════════════════════════════════════════════════════

async def set_profile_hidden(user_id: str, hidden: bool) -> None:
    """Пауза аккаунта: скрыть анкету из поиска или вернуть её.

    Пишем в `is_paused`, а не в `is_incognito`. Из деки убирают оба флага, но
    смыслы разные: инкогнито — платная функция Plus, пауза — базовое право
    уйти. Пока они делили одно поле, команда /pause бесплатно включала то, что
    в мини-аппе стоит денег.
    """
    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            result = await session.execute(
                select(Profile).where(Profile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile:
                profile.is_paused = hidden


async def is_profile_hidden(user_id: str) -> bool:
    """На паузе ли анкета. Инкогнито здесь не смотрим: это другая функция,
    и /resume не должен снимать платную настройку."""
    cls = _session_cls()
    async with cls() as session:
        result = await session.execute(
            select(Profile.is_paused).where(Profile.user_id == user_id)
        )
        return bool(result.scalar())


async def delete_user_account(user_id: str) -> bool:
    """Полностью удалить пользователя и все его данные.

    Обязательная возможность по требованиям App Store (5.1.1(v)).
    Связанные записи удаляются каскадом на уровне БД.
    """
    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                return False
            await session.delete(user)
    return True


# ════════════════════════════════════════════════════════════════
#  ЖАЛОБЫ
# ════════════════════════════════════════════════════════════════

async def create_report(
    reporter_id: str, reported_id: str, reason: str, description: str = ""
) -> bool:
    """Создать жалобу с той же эскалацией, что в API.

    Порог считается по числу РАЗНЫХ жалобщиков, иначе один человек мог бы
    забанить другого повторными обращениями: 3+ — анкета скрывается из
    выдачи до решения модератора, 5+ — автобан.
    """
    if reporter_id == reported_id:
        return False

    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            # Повторную жалобу от того же человека не дублируем
            existing = await session.execute(
                select(Report).where(
                    Report.reporter_id == reporter_id,
                    Report.reported_id == reported_id,
                    Report.status == "pending",
                )
            )
            if existing.scalar_one_or_none() is None:
                session.add(
                    Report(
                        reporter_id=reporter_id,
                        reported_id=reported_id,
                        reason=reason,
                        description=description[:500],
                    )
                )
                await session.flush()

            counted = await session.execute(
                select(func.count(func.distinct(Report.reporter_id))).where(
                    Report.reported_id == reported_id,
                    Report.status == "pending",
                    # В счёт идут только те, кто реально пересекался с целью:
                    # иначе пять свежих аккаунтов банят любого за секунды
                    or_(
                        select(Like.liker_id)
                        .where(
                            Like.liked_id == reported_id,
                            Like.liker_id == Report.reporter_id,
                        )
                        .exists(),
                        select(Like.liked_id)
                        .where(
                            Like.liker_id == reported_id,
                            Like.liked_id == Report.reporter_id,
                        )
                        .exists(),
                        select(Match.id)
                        .where(
                            or_(
                                and_(
                                    Match.user1_id == reported_id,
                                    Match.user2_id == Report.reporter_id,
                                ),
                                and_(
                                    Match.user2_id == reported_id,
                                    Match.user1_id == Report.reporter_id,
                                ),
                            )
                        )
                        .exists(),
                    ),
                )
            )
            distinct_reporters = counted.scalar() or 0

            if distinct_reporters >= 5:
                target = await session.execute(
                    select(User).where(User.id == reported_id)
                )
                user = target.scalar_one_or_none()
                if user:
                    user.is_banned = True
            elif distinct_reporters >= 3:
                target = await session.execute(
                    select(Profile).where(Profile.user_id == reported_id)
                )
                profile = target.scalar_one_or_none()
                if profile:
                    profile.is_incognito = True
    return True


# ════════════════════════════════════════════════════════════════
#  BLOCKS
# ════════════════════════════════════════════════════════════════

async def block_user(blocker_id: str, blocked_id: str) -> bool:
    """Заблокировать навсегда: пара исчезает из выдачи друг друга.

    В отличие от жалобы (уходит модератору) действует сразу, и в отличие
    от размэтча необратима для второй стороны. Мэтч деактивируется, лайки
    в обе стороны удаляются — иначе после снятия блокировки пара
    смэтчилась бы заново старыми лайками.
    """
    if blocker_id == blocked_id:
        return False

    from sqlalchemy.exc import IntegrityError

    cls = _session_cls()
    async with cls() as session:
        try:
            async with session.begin():
                session.add(Block(blocker_id=blocker_id, blocked_id=blocked_id))
        except IntegrityError:
            await session.rollback()
            return True  # уже заблокирован — результат тот же

        async with session.begin():
            u1, u2 = (
                (blocker_id, blocked_id)
                if blocker_id < blocked_id
                else (blocked_id, blocker_id)
            )
            result = await session.execute(
                select(Match).where(Match.user1_id == u1, Match.user2_id == u2)
            )
            match = result.scalar_one_or_none()
            if match:
                match.is_active = False

            await session.execute(
                Like.__table__.delete().where(
                    or_(
                        and_(Like.liker_id == blocker_id, Like.liked_id == blocked_id),
                        and_(Like.liker_id == blocked_id, Like.liked_id == blocker_id),
                    )
                )
            )
        return True


async def get_active_subscription(user_id: str) -> dict | None:
    cls = _session_cls()
    async with cls() as session:
        result = await session.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        sub = result.scalar_one_or_none()
        if not sub or sub.plan == "free":
            return None
        if sub.expires_at and sub.expires_at.replace(tzinfo=None) < datetime.utcnow():
            return None
        return {
            "plan": sub.plan,
            "expires_at": sub.expires_at.isoformat() if sub.expires_at else None,
        }


async def activate_premium(
    user_id: str,
    days: int = 30,
    payment_id: str = "",
    provider: str = "stars",
    tier: str = "plus",
) -> dict:
    """Активировать/продлить Premium.

    Идемпотентность держится на уникальном ключе (provider, external_id) в
    dating_processed_payments, а не на сравнении с последним payment_id: инвойс
    CryptoBot остаётся оплаченным навсегда, кнопку «Проверить оплату» можно
    нажать повторно, и без журнала повторное нажатие начисляло премиум заново.
    """
    from datetime import timedelta

    from sqlalchemy.exc import IntegrityError

    cls = _session_cls()
    async with cls() as session:
        # Платёж помечается зачтённым в отдельной транзакции: при гонке двух
        # одновременных проверок одного инвойса второй INSERT упадёт на
        # уникальном ключе и начисления не будет.
        if payment_id:
            try:
                async with session.begin():
                    session.add(
                        ProcessedPayment(
                            provider=provider,
                            external_id=payment_id,
                            user_id=user_id,
                            days=days,
                        )
                    )
            except IntegrityError:
                await session.rollback()
                result = await session.execute(
                    select(Subscription).where(Subscription.user_id == user_id)
                )
                sub = result.scalar_one_or_none()
                return {
                    "plan": sub.plan if sub else "free",
                    "expires_at": sub.expires_at.isoformat() if sub and sub.expires_at else "",
                    "already_processed": True,
                }

        async with session.begin():
            result = await session.execute(
                select(Subscription).where(Subscription.user_id == user_id)
            )
            sub = result.scalar_one_or_none()

            now = datetime.utcnow()
            if not sub:
                sub = Subscription(user_id=user_id)
                session.add(sub)

            # Продление поверх остатка, а не с текущей даты
            base = now
            if sub.expires_at:
                current = sub.expires_at.replace(tzinfo=None)
                if current > now:
                    base = current

            # Уровень не понижаем задним числом: купивший Ultra и продливший
            # затем Plus добавляет срок, но не теряет уплаченный уровень
            if tier_rank(tier) >= tier_rank(sub.plan or "free"):
                sub.plan = tier
            sub.stripe_id = payment_id or sub.stripe_id
            sub.expires_at = base + timedelta(days=days)
            await session.flush()
            return {"plan": sub.plan, "expires_at": sub.expires_at.isoformat()}


async def revoke_premium_payment(payment_id: str, provider: str = "stars") -> dict:
    """Откатить подписку после возврата денег.

    Telegram позволяет вернуть Stars, и тогда боту приходит `refunded_payment`.
    Без этого подписка оставалась активной до конца оплаченного срока, хотя
    деньги уже вернулись пользователю: оплатил, получил Ultra, вернул Stars —
    и пользуешься дальше бесплатно.

    Срок урезаем ровно на те дни, что были начислены этим платежом, а не
    гасим подписку целиком: у человека рядом могла быть другая, честно
    оплаченная покупка, и отнимать её нельзя. Запись платежа удаляем, чтобы
    возвращённый и заново оплаченный тот же charge_id снова зачёлся.
    """
    from datetime import timedelta

    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            result = await session.execute(
                select(ProcessedPayment).where(
                    and_(
                        ProcessedPayment.provider == provider,
                        ProcessedPayment.external_id == payment_id,
                    )
                )
            )
            платёж = result.scalar_one_or_none()
            if not платёж:
                # Возврат платежа, которого мы не зачитывали, — ничего не должны
                return {"revoked": False, "reason": "платёж не найден"}

            result = await session.execute(
                select(Subscription).where(Subscription.user_id == платёж.user_id)
            )
            sub = result.scalar_one_or_none()

            if sub and sub.expires_at:
                сокращённый = sub.expires_at - timedelta(days=платёж.days or 0)
                now = datetime.utcnow()
                if сокращённый <= now:
                    # Оплаченного срока не осталось — уровень падает до
                    # бесплатного, иначе Ultra висел бы с истёкшей датой
                    sub.expires_at = now
                    sub.plan = "free"
                else:
                    sub.expires_at = сокращённый

            await session.delete(платёж)
            await session.flush()
            return {
                "revoked": True,
                "user_id": платёж.user_id,
                "days": платёж.days or 0,
                "plan": sub.plan if sub else "free",
            }


# ════════════════════════════════════════════════════════════════
#  LIKES & MATCHES
# ════════════════════════════════════════════════════════════════

async def like_and_match(
    liker_id: str, liked_id: str, like_type: str = "like", message: str = "",
) -> dict:
    """Поставить лайк и, если он взаимный, создать мэтч — одной транзакцией.

    Раньше это были три независимые транзакции (create_like →
    check_mutual_like → create_match) без блокировки, и два встречных лайка
    в один момент не видели друг друга при READ COMMITTED: оба получали
    «взаимности нет», мэтч терялся насовсем. Advisory-lock на нормализованную
    пару — тот же, что в api/routers/likes.py, поэтому лайки из бота и из веба
    сериализуются между собой.

    Возвращает: matched — создан/подтверждён мэтч, match — данные мэтча,
    upgraded — прежний pass заменён на лайк.
    """
    u1, u2 = (liker_id, liked_id) if liker_id < liked_id else (liked_id, liker_id)
    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": f"dating:pair:{u1}:{u2}"},
            )

            result = await session.execute(
                select(Like).where(Like.liker_id == liker_id, Like.liked_id == liked_id)
            )
            existing = result.scalar_one_or_none()

            upgraded = False
            if existing:
                if existing.type != like_type:
                    # Смена решения: pass → like должен приводить к мэтчу,
                    # иначе повторный лайк после пропуска молча терялся
                    existing.type = like_type
                    upgraded = True
                # Пустым текстом прежний не затираем: человек мог написать
                # пару слов, а потом просто сменить тип лайка
                if message:
                    existing.message = message
            else:
                session.add(Like(
                    liker_id=liker_id,
                    liked_id=liked_id,
                    type=like_type,
                    message=message,
                ))
            await session.flush()

            if like_type == "pass":
                return {"matched": False, "match": None, "upgraded": upgraded}

            result = await session.execute(
                select(Like).where(
                    Like.liker_id == liked_id,
                    Like.liked_id == liker_id,
                    Like.type != "pass",
                )
            )
            if not result.scalar_one_or_none():
                return {"matched": False, "match": None, "upgraded": upgraded}

            result = await session.execute(
                select(Match).where(Match.user1_id == u1, Match.user2_id == u2)
            )
            match = result.scalar_one_or_none()
            is_new = False
            if match is None:
                match = Match(user1_id=u1, user2_id=u2, is_active=True)
                session.add(match)
                await session.flush()
                is_new = True
            elif not match.is_active:
                match.is_active = True
                is_new = True

            return {
                "matched": True,
                "is_new": is_new,
                "upgraded": upgraded,
                "match": {
                    "id": match.id,
                    "user1_id": match.user1_id,
                    "user2_id": match.user2_id,
                    "match_score": match.match_score,
                },
            }


def _дата_рождения_для(лет: int) -> datetime:
    """Дата, когда родился человек, которому сегодня исполняется `лет`.

    Через `replace(year=...)` нельзя: 29 февраля оно падает с ValueError на
    невисокосном году — и дека перестала бы открываться у всех, но только раз
    в четыре года, то есть нашлось бы это в проде.
    """
    сегодня = datetime.now()
    try:
        return сегодня.replace(year=сегодня.year - лет)
    except ValueError:
        # 29 февраля → 28-е: сдвиг на сутки в границе окна незаметен
        return сегодня.replace(year=сегодня.year - лет, day=28)


async def get_deck_profiles(user_id: str, limit: int = 5) -> list[dict]:
    """Анкеты для показа в боте: фильтр по предпочтениям + сортировка по интересам."""
    cls = _session_cls()
    async with cls() as session:
        result = await session.execute(
            select(Profile).where(Profile.user_id == user_id)
        )
        my = result.scalar_one_or_none()

        # Get already liked
        result = await session.execute(
            select(Like.liked_id).where(Like.liker_id == user_id)
        )
        exclude_ids = {row[0] for row in result.all()} | {user_id}

        # Блокировки — в обе стороны, иначе жертва снова увидит обидчика
        result = await session.execute(
            select(Block.blocked_id).where(Block.blocker_id == user_id)
        )
        exclude_ids |= {row[0] for row in result.all()}
        result = await session.execute(
            select(Block.blocker_id).where(Block.blocked_id == user_id)
        )
        exclude_ids |= {row[0] for row in result.all()}

        # Кто поставил мне «пропустить» — взаимности уже не будет,
        # показывать их анкеты значит тратить деку впустую
        result = await session.execute(
            select(Like.liker_id).where(
                Like.liked_id == user_id, Like.type == "pass"
            )
        )
        exclude_ids |= {row[0] for row in result.all()}

        filters = [
            User.is_banned == False,
            # Инкогнито и пауза убирают из деки одинаково — см. api/models
            Profile.is_incognito == False,
            Profile.is_paused == False,
            Profile.display_name != "",  # пустые анкеты не показываем
            Profile.user_id.notin_(exclude_ids) if exclude_ids else True,
        ]
        if my and my.looking_for and my.looking_for != "any":
            filters.append(Profile.gender.in_([my.looking_for, "other"]))

        # Возрастной диапазон — самый базовый фильтр дейтинга, и он задаётся
        # в мини-аппе. Без него человек выставил «25-30» в приложении, а бот
        # показывал всех подряд. Считаем по дате рождения: границы окна —
        # это «сегодня минус N лет».
        if my and (my.age_min or my.age_max):
            if my.age_max:
                # Кто старше верхней границы — родился раньше этой даты
                filters.append(Profile.birth_date >= _дата_рождения_для(my.age_max + 1))
            if my.age_min:
                filters.append(Profile.birth_date <= _дата_рождения_для(my.age_min))

        # Нишевые фильтры задаются в мини-аппе, а действовать должны и здесь:
        # иначе человек выставил «гот» в приложении, а бот показывает всех.
        # Анкеты с незаполненным полем не отсеиваем — они не виноваты, что
        # графа пустая, и иначе выдача схлопнулась бы почти до нуля.
        if my and my.filter_goal:
            filters.append(Profile.goal.in_([my.filter_goal, ""]))
        if my and my.filter_subculture:
            filters.append(Profile.subculture.in_([my.filter_subculture, ""]))
        if my and my.filter_city:
            filters.append(func.lower(Profile.city) == my.filter_city.strip().lower())
        # Рост — исключение: если диапазон задан, анкеты без роста проверить
        # нечем, поэтому они выпадают.
        if my and (my.filter_height_min or my.filter_height_max):
            filters.append(Profile.height_cm.isnot(None))
            if my.filter_height_min:
                filters.append(Profile.height_cm >= my.filter_height_min)
            if my.filter_height_max:
                filters.append(Profile.height_cm <= my.filter_height_max)

        # Выборка от случайной точки sample_key по индексу вместо
        # ORDER BY RANDOM(): тому нужна сортировка всей таблицы на каждый
        # показ анкеты. У конца диапазона строк не хватит — добираем
        # с начала, иначе анкеты с большим ключом видели бы полупустую деку.
        async def _scan(*extra) -> list[Profile]:
            result = await session.execute(
                select(Profile)
                .join(User, Profile.user_id == User.id)
                .where(*filters, *extra)
                .order_by(Profile.sample_key)
                .limit(limit * 3)
            )
            return list(result.scalars().all())

        cut = random.random()
        rows = await _scan(Profile.sample_key >= cut)
        if len(rows) < limit * 3:
            rows += await _scan(Profile.sample_key < cut)

        profiles = [_profile_to_dict(p) for p in rows[: limit * 3]]

        # Встречный фильтр + сортировка по общим интересам
        my_gender = my.gender if my else "other"
        my_interests = set(
            (my.interests if isinstance(my.interests, list) else []) if my else []
        )

        def _visible(p: dict) -> bool:
            lf = p.get("looking_for") or "any"
            return lf == "any" or lf == my_gender or my_gender == "other"

        profiles = [p for p in profiles if _visible(p)]
        profiles.sort(
            key=lambda p: len(my_interests & set(p.get("interests") or [])),
            reverse=True,
        )
        return profiles[:limit]


async def get_match_partner(match_id: str, user_id: str) -> dict | None:
    """Get the other user in a match.

    Возвращает None, если мэтч не существует, разорван или user_id
    не является его участником (защита от подстановки чужого match_id).
    """
    cls = _session_cls()
    async with cls() as session:
        result = await session.execute(
            select(Match).where(Match.id == match_id)
        )
        match = result.scalar_one_or_none()
        if not match or not match.is_active:
            return None
        if user_id not in (match.user1_id, match.user2_id):
            return None

        partner_id = match.user2_id if match.user1_id == user_id else match.user1_id
        return await get_profile(partner_id)


async def get_user_matches(user_id: str) -> list[dict]:
    """Get all matches for a user."""
    cls = _session_cls()
    async with cls() as session:
        result = await session.execute(
            select(Match).where(
                (Match.user1_id == user_id) | (Match.user2_id == user_id),
                Match.is_active == True,
            ).order_by(Match.created_at.desc())
        )
        matches = result.scalars().all()
        return [
            {
                "id": m.id,
                "partner_id": m.user2_id if m.user1_id == user_id else m.user1_id,
                "match_score": m.match_score,
                "ai_reason": m.ai_reason,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in matches
        ]


# ════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════

def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "role": user.role,
        "is_banned": user.is_banned,
        "is_verified": user.is_verified,
        "last_seen_at": user.last_seen_at.isoformat() if user.last_seen_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _profile_to_dict(profile: Profile) -> dict:
    photos = profile.photos if isinstance(profile.photos, list) else json.loads(profile.photos or "[]")
    interests = profile.interests if isinstance(profile.interests, list) else json.loads(profile.interests or "[]")

    # «Скрыть возраст» должно действовать и в боте: в мини-аппе возраст
    # скрытым не отдаётся (api/services/public_profile.py), а бот считал его
    # сам и показывал всем — настройка обещает «скрыто», а не «скрыто в вебе»
    age = None
    if profile.birth_date and not getattr(profile, "hide_age", False):
        now = datetime.now()
        age = now.year - profile.birth_date.year
        if (now.month, now.day) < (profile.birth_date.month, profile.birth_date.day):
            age -= 1

    return {
        "user_id": profile.user_id,
        "display_name": profile.display_name or "",
        "bio": profile.bio or "",
        "gender": profile.gender or "other",
        "age": age,
        "city": profile.city or "",
        "photos": photos,
        "interests": interests,
        "ai_bio": profile.ai_bio,
        "looking_for": profile.looking_for,
        "goal": profile.goal or "",
        "subculture": profile.subculture or "",
        "mbti": profile.mbti or "",
        "height_cm": profile.height_cm,
        # Наклейка из коллекции: в боте картинку не показать (это SVG в вебе),
        # поэтому в текстовой карточке она отмечается значком редкости —
        # см. texts.ЗНАЧОК_НАКЛЕЙКИ
        "sticker": profile.sticker or "",
    }
