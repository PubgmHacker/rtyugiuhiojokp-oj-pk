from __future__ import annotations

import hashlib
import json
import logging
import random
from datetime import datetime, timezone

from sqlalchemy import select, text, func, and_, not_, or_, case, delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import DATABASE_URL
from services.plans import tier_from_plan, tier_rank

# Список языков берём из texts: там его единственная копия на стороне бота —
# по ней же рисуется сетка кнопок онбординга, и собственная копия здесь
# разъехалась бы с ней при первом добавленном языке. Цикла нет: texts тянет
# только services.plans, который мы импортируем строкой выше.
from texts import ONBOARDING_LOCALES as ЯЗЫКИ

# Модулем, а не именами: `services/quotas.py` импортирует `database.models`, а
# это поднимает пакет `database` целиком — то есть нас же. `from ... import
# likes_state` требует атрибут в момент импорта и падает на полупустом модуле;
# `import ... as` привязывает сам модуль, а имена берёт при вызове.
import services.quotas as quotas

from database.models import (
    AiModerationLog,
    AnalyticsEvent,
    BannedIdentity,
    Base,
    Block,
    GiftSubscription,
    User,
    Profile,
    Like,
    Match,
    ProcessedPayment,
    PromoActivation,
    PromoCode,
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
                # Временный бан истёк — снимаем прямо здесь, как API в
                # get_current_user: фонового джоба нет, а /start забаненного —
                # ровно тот момент, когда срок пора проверить. Чистим и память
                # банов: иначе удаление аккаунта воскресило бы отбытый бан.
                if user.is_banned and user.banned_until is not None:
                    срок = (
                        user.banned_until
                        if user.banned_until.tzinfo
                        else user.banned_until.replace(tzinfo=timezone.utc)
                    )
                    if срок <= datetime.now(timezone.utc):
                        user.is_banned = False
                        user.banned_until = None
                        conds = [BannedIdentity.telegram_id == telegram_id]
                        if user.apple_id:
                            conds.append(BannedIdentity.apple_id == user.apple_id)
                        await session.execute(
                            delete(BannedIdentity).where(or_(*conds))
                        )
                        logger.info(f"Бан истёк и снят в боте: user={user.id}")
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


async def set_user_locale(telegram_id: int, locale: str) -> bool:
    """Запомнить выбранный на онбординге язык на аккаунте.

    До этого выбор жил только в FSM-состоянии: перезапуск бота, смена storage
    или истечение ключа — и человек, выбравший узбекский, продолжал на русском,
    а мини-апп о выборе не узнавал вообще.

    Пишем по telegram_id, а не по внутреннему id: обработчик онбординга знает
    только Telegram-аккаунт. Возвращаем False, если строки нет — это не ошибка
    сценария, а сигнал вызывающему не считать язык сохранённым.
    """
    if locale not in ЯЗЫКИ:
        # Молча не подставляем русский: неизвестный код — это рассинхрон
        # клавиатуры бота с этим списком, и он должен быть виден в логах,
        # а не превращаться в тихую потерю языка
        logger.warning("не сохранили неизвестный язык %r для %s", locale, telegram_id)
        return False

    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if not user:
                return False
            user.locale = locale
            await session.flush()
            return True


async def get_user_locale(telegram_id: int) -> str | None:
    """Язык аккаунта по Telegram-id, или None, если аккаунта ещё нет.

    Нужен там, где FSM пуст, а язык всё равно обязан быть правильным: тап по
    старой кнопке через неделю, рестарт бота посреди онбординга. None, а не
    "ru", чтобы вызывающий сам решил, чем подставлять — тихий русский вместо
    выбранного языка и есть та ошибка, которую эта колонка закрывает.
    """
    cls = _session_cls()
    async with cls() as session:
        result = await session.execute(
            select(User.locale).where(User.telegram_id == telegram_id)
        )
        язык = result.scalar_one_or_none()
        return язык if язык in ЯЗЫКИ else None


async def get_profile(user_id: str) -> dict | None:
    cls = _session_cls()
    async with cls() as session:
        # Галочка живёт на User, а не на Profile — забираем её тем же
        # запросом: через get_profile рисуются карточка партнёра и своя
        # анкета, и ✅ должен быть виден везде одинаково
        result = await session.execute(
            select(Profile, User.is_verified)
            .join(User, Profile.user_id == User.id)
            .where(Profile.user_id == user_id)
        )
        row = result.first()
        if not row:
            return None
        profile, is_verified = row
        данные = _profile_to_dict(profile)
        данные["is_verified"] = bool(is_verified)
        return данные


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


# set_profile_ready здесь больше нет — она ставила is_verified каждому, кто
# дошёл до конца анкеты, и галочка «проверенный» врала. Теперь её выдаёт
# только живая проверка лица (api/routers/verification.py).


async def clear_verification(user_id: str) -> None:
    """Снять галочку «проверенный» вместе с опорным фото.

    Галочка обещает, что все фото анкеты принадлежат человеку, прошедшему
    живую проверку. Сверять лица умеет только API (сверка добавленного фото
    с опорным в api/routers/profiles.py) — бот при изменении состава фото
    галочку честно снимает, повторная проверка в мини-аппе вернёт её.
    Опорное фото обнуляем той же транзакцией: галочка и опорное живут
    только парой, половинчатое состояние ломало бы сверку в API.
    """
    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user:
                user.is_verified = False
            result = await session.execute(
                select(Profile).where(Profile.user_id == user_id)
            )
            profile = result.scalar_one_or_none()
            if profile:
                profile.verified_photo = ""


# ════════════════════════════════════════════════════════════════
#  ДОСРОЧНАЯ РАЗБЛОКИРОВКА (платная)
# ════════════════════════════════════════════════════════════════

async def unban_after_payment(
    user_id: str, charge_id: str, price_rub: int, stars: int | None = None,
) -> dict:
    """Снять бан после оплаченной досрочной разблокировки.

    Возвращает {"unbanned": bool, "reason": str}. "not_banned" — деньги
    пришли, а снимать нечего (двойная оплата, разбан админом): вызывающий
    обязан вернуть Stars. "already_processed" — Telegram повторил доставку
    УЖЕ зачтённого апдейта: вызывающий НЕ возвращает Stars — услуга по этому
    charge_id оказана, возврат делал бы разбан бесплатным через ретрай.

    Проверка журнала — ДО проверки бана: повтор старого апдейта после
    повторного бана иначе снимал бы новый бан старыми деньгами.

    Одной транзакцией:
    * флаг is_banned;
    * память банов (dating_banned_identities) — без чистки разбан жил бы до
      первого удаления аккаунта: привязки продолжали бы держать бан;
    * запись unban_purchase в журнал модерации — от неё API считает новое
      окно страйков за чужое лицо (api/services/enforcement.py). Без этой
      амнистии первый же спорный кадр после оплаты банил бы обратно,
      и покупка была бы ловушкой.

    Отзыв токенов не трогаем: отметка отзыва гасит только токены, выданные
    ДО бана, а свежий вход после разблокировки получает живой токен сам.
    """
    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            уже = await session.scalar(
                select(ProcessedPayment).where(
                    ProcessedPayment.provider == "stars",
                    ProcessedPayment.external_id == charge_id,
                )
            )
            if уже is not None:
                return {"unbanned": False, "reason": "already_processed"}

            result = await session.execute(select(User).where(User.id == user_id))
            user = result.scalar_one_or_none()
            if user is None:
                return {"unbanned": False, "reason": "no_user"}
            if not user.is_banned:
                return {"unbanned": False, "reason": "not_banned"}

            user.is_banned = False
            user.banned_until = None

            conds = []
            if user.telegram_id:
                conds.append(BannedIdentity.telegram_id == user.telegram_id)
            if user.apple_id:
                conds.append(BannedIdentity.apple_id == user.apple_id)
            if conds:
                await session.execute(delete(BannedIdentity).where(or_(*conds)))

            session.add(
                AiModerationLog(
                    user_id=user_id,
                    content_type="unban_purchase",
                    content=charge_id,
                    result="safe",
                    action="none",
                    reason=f"досрочная разблокировка за {price_rub} ₽",
                )
            )

            # Журнал платежей — для выручки в админке (``stars`` — фактически
            # уплаченные Stars из successful_payment). days=0: разбан не
            # двигает подписку. В savepoint: дубль апдейта Telegram упадёт на
            # уникальном ключе (provider, external_id) и не откатит разбан
            if stars:
                from sqlalchemy.exc import IntegrityError

                try:
                    async with session.begin_nested():
                        session.add(
                            ProcessedPayment(
                                provider="stars",
                                external_id=charge_id,
                                user_id=user_id,
                                days=0,
                                amount=stars,
                                currency="XTR",
                            )
                        )
                except IntegrityError:
                    pass

    logger.warning(f"Разбан по оплате: user={user_id} charge={charge_id}")
    return {"unbanned": True, "reason": ""}


async def reban_after_refund(charge_id: str) -> dict:
    """Вернуть бан после возврата Stars за досрочную разблокировку.

    Без этого возврат делал разблокировку бесплатной: оплатил, разбанился,
    вернул Stars через поддержку Telegram — и остался разбаненным.

    Платёж ищем по журналу модерации (unban_purchase хранит charge_id):
    сам возврат Telegram не говорит, чей он и за что. Возвращает
    {"rebanned": bool, "user_id": str, "telegram_id": int} — привязки нужны
    вызывающему для уведомления и отзыва токенов.
    """
    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            result = await session.execute(
                select(AiModerationLog).where(
                    AiModerationLog.content_type == "unban_purchase",
                    AiModerationLog.content == charge_id,
                )
            )
            покупка = result.scalars().first()
            if покупка is None:
                return {"rebanned": False, "user_id": "", "telegram_id": 0}

            # Деньги вернулись — из журнала выручки платёж уходит (как
            # revoke_premium_payment в API удаляет строку подписки). До
            # проверок пользователя: выручка корректируется, даже если
            # возвращать бан уже некому
            result = await session.execute(
                select(ProcessedPayment).where(
                    ProcessedPayment.provider == "stars",
                    ProcessedPayment.external_id == charge_id,
                )
            )
            платёж = result.scalars().first()
            if платёж is not None:
                await session.delete(платёж)

            result = await session.execute(
                select(User).where(User.id == покупка.user_id)
            )
            user = result.scalar_one_or_none()
            if user is None or user.is_banned:
                # Уже забанен заново или удалился — возвращать бан некому
                return {"rebanned": False, "user_id": "", "telegram_id": 0}

            # Вечный, без лестницы: возврат денег за разбан — не «нарушение
            # поведения», а обман платежом, и срок тут выторговывать нечего
            user.is_banned = True
            user.banned_until = None

            # Память банов: та же пара привязок, что при обычном бане.
            # Существующую строку обновляем, а не пропускаем: в ней мог
            # остаться короткий (или истёкший) срок прежнего бана, и он
            # отпустил бы возвращенца раньше времени.
            if user.telegram_id:
                result = await session.execute(
                    select(BannedIdentity).where(
                        BannedIdentity.telegram_id == user.telegram_id
                    )
                )
                строка = result.scalars().first()
                if строка is None:
                    session.add(
                        BannedIdentity(
                            telegram_id=user.telegram_id,
                            reason="возврат платежа за досрочную разблокировку",
                        )
                    )
                else:
                    строка.reason = "возврат платежа за досрочную разблокировку"
                    строка.banned_until = None

            # След в журнале: спорные разбаны-возвраты разбираются постфактум
            session.add(
                AiModerationLog(
                    user_id=user.id,
                    content_type="unban_refund",
                    content=charge_id,
                    result="blocked",
                    action="ban",
                    reason="возврат Stars за досрочную разблокировку",
                )
            )

            итог = {
                "rebanned": True,
                "user_id": user.id,
                "telegram_id": user.telegram_id or 0,
            }

    logger.warning(f"Бан возвращён после возврата Stars: charge={charge_id}")
    return итог


# ════════════════════════════════════════════════════════════════
#  ПАКИ ЗА STARS (суперлайки и бусты)
# ════════════════════════════════════════════════════════════════

async def credit_pack(
    user_id: str, charge_id: str, kind: str, qty: int, stars: int,
) -> dict:
    """Начислить купленный пак: суперлайки или включения буста.

    Возвращает {"credited": bool, "reason": str, "balance": int}.
    "already_processed" — этот charge_id уже зачтён (дубль апдейта
    Telegram), "no_profile" — анкеты нет и класть бонус некуда: деньги
    списаны, вызывающий обязан вернуть Stars.

    Идемпотентность — той же строкой журнала платежей, что у подписок и
    разбана: unique(provider, external_id). Здесь она маркер зачёта, а не
    примечание, поэтому НЕ в savepoint: упала запись платежа — откатилось и
    начисление, второй successful_payment зачтёт всё заново. Два зачёта в
    полёте одновременно разводит тот же unique: проигравший откатывается
    целиком и приходит сюда IntegrityError.
    """
    from sqlalchemy.exc import IntegrityError

    cls = _session_cls()
    try:
        async with cls() as session:
            async with session.begin():
                result = await session.execute(
                    select(Profile).where(Profile.user_id == user_id)
                )
                профиль = result.scalar_one_or_none()
                if профиль is None:
                    return {"credited": False, "reason": "no_profile", "balance": 0}

                result = await session.execute(
                    select(ProcessedPayment).where(
                        ProcessedPayment.provider == "stars",
                        ProcessedPayment.external_id == charge_id,
                    )
                )
                if result.scalars().first() is not None:
                    return {
                        "credited": False,
                        "reason": "already_processed",
                        "balance": 0,
                    }

                # days=0: пак не двигает подписку. amount — фактически
                # уплаченные Stars из successful_payment, по ним админка
                # считает выручку
                session.add(
                    ProcessedPayment(
                        provider="stars",
                        external_id=charge_id,
                        user_id=user_id,
                        days=0,
                        amount=stars,
                        currency="XTR",
                    )
                )

                if kind == "boosts":
                    профиль.bonus_boosts = (профиль.bonus_boosts or 0) + qty
                    баланс = профиль.bonus_boosts
                else:
                    профиль.bonus_superlikes = (профиль.bonus_superlikes or 0) + qty
                    баланс = профиль.bonus_superlikes
    except IntegrityError:
        return {"credited": False, "reason": "already_processed", "balance": 0}

    logger.info(
        f"Пак начислен: user={user_id} charge={charge_id} {kind}+{qty} "
        f"баланс={баланс}"
    )
    return {"credited": True, "reason": "", "balance": баланс}


async def revoke_pack(charge_id: str, kind: str, qty: int) -> dict:
    """Списать пак после возврата Stars.

    Возвращает {"revoked": bool, "user_id": str}. Платёж ищем по журналу
    выручки — сам возврат Telegram говорит только payload и charge_id.
    Строка платежа удаляется (выручка корректируется, как у подписок), а
    баланс срезается не ниже нуля: купленное могли уже потратить, и уводить
    счётчик в минус значило бы отбирать суточную квоту.
    """
    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            result = await session.execute(
                select(ProcessedPayment).where(
                    ProcessedPayment.provider == "stars",
                    ProcessedPayment.external_id == charge_id,
                )
            )
            платёж = result.scalars().first()
            if платёж is None:
                # Уже возвращён или зачёт не состоялся — списывать нечего
                return {"revoked": False, "user_id": ""}

            user_id = платёж.user_id
            await session.delete(платёж)

            result = await session.execute(
                select(Profile).where(Profile.user_id == user_id)
            )
            профиль = result.scalar_one_or_none()
            if профиль is not None:
                if kind == "boosts":
                    профиль.bonus_boosts = max(0, (профиль.bonus_boosts or 0) - qty)
                else:
                    профиль.bonus_superlikes = max(
                        0, (профиль.bonus_superlikes or 0) - qty
                    )

    logger.warning(f"Пак списан после возврата: charge={charge_id} {kind}-{qty}")
    return {"revoked": True, "user_id": user_id}


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
                    # Память банов — как у банов API (services/enforcement.py):
                    # без неё этот бан снимался бы бесплатно удалением аккаунта
                    # (каскад стирает флаг), и платная досрочная разблокировка
                    # теряла бы смысл. Дубль не пишем: telegram_id уникален.
                    if user.telegram_id:
                        существует = await session.execute(
                            select(BannedIdentity.id).where(
                                BannedIdentity.telegram_id == user.telegram_id
                            )
                        )
                        if существует.scalar_one_or_none() is None:
                            session.add(
                                BannedIdentity(
                                    telegram_id=user.telegram_id,
                                    reason="жалобы нескольких пользователей",
                                )
                            )
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


# ── Событийная аналитика ─────────────────────────────────────────
# Зеркало api/services/analytics.py::track: имена событий, формат dedup_key
# и таблица общие — отчёты читают воронку из обеих половин (бот и API).
# Полный словарь событий и SQL отчётов — в docstring того модуля.


async def _track_event_in(
    session: AsyncSession,
    user_id: str,
    event: str,
    props: dict | None = None,
    *,
    once: bool = False,
    daily: bool = False,
) -> None:
    """Записать событие в уже открытую транзакцию — коммитится с делом.

    `once` — веха: одна строка на человека за всю жизнь (первый /start).
    `daily` — одна строка на календарный день UTC. Повторы гасит dedup_key:
    предпроверка SELECT'ом (иначе каждый повторный /start шёл бы через
    duplicate key — Postgres пишет такой конфликт ошибкой в свой лог),
    гонку двух первых вызовов ловит уникальный ключ внутри savepoint.
    """
    from sqlalchemy.exc import IntegrityError

    dedup: str | None = None
    if once:
        dedup = f"{user_id}:{event}"
    elif daily:
        день = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        dedup = f"{user_id}:{event}:{день}"

    try:
        if dedup is not None:
            существует = await session.execute(
                select(AnalyticsEvent.id).where(AnalyticsEvent.dedup_key == dedup)
            )
            if существует.scalar_one_or_none() is not None:
                return
        # Savepoint, не транзакция: при повторе вехи откатывается только
        # INSERT события, бизнес-изменения вызывающего остаются целы
        async with session.begin_nested():
            session.add(AnalyticsEvent(
                user_id=user_id,
                event=event,
                props=props or {},
                dedup_key=dedup,
            ))
    except IntegrityError:
        pass  # веха уже записана — повтор не событие
    except Exception as e:
        # Аналитика не смеет ломать продукт: начисление важнее строки в отчёте
        logger.warning(f"Событие {event} не записано (user={user_id}): {e}")


async def track_event(
    user_id: str,
    event: str,
    props: dict | None = None,
    *,
    once: bool = False,
    daily: bool = False,
) -> None:
    """Записать событие собственной сессией — для хендлеров вне транзакций.

    Никогда не поднимает исключений: /start обязан ответить человеку и при
    лежащей аналитике.
    """
    try:
        cls = _session_cls()
        async with cls() as session:
            async with session.begin():
                await _track_event_in(
                    session, user_id, event, props, once=once, daily=daily
                )
    except Exception as e:
        logger.warning(f"Событие {event} не записано (user={user_id}): {e}")


async def activate_premium(
    user_id: str,
    days: int = 30,
    payment_id: str = "",
    provider: str = "stars",
    tier: str = "plus",
    amount: int | None = None,
    currency: str | None = None,
) -> dict:
    """Активировать/продлить Premium.

    Идемпотентность держится на уникальном ключе (provider, external_id) в
    dating_processed_payments, а не на сравнении с последним payment_id: инвойс
    CryptoBot остаётся оплаченным навсегда, кнопку «Проверить оплату» можно
    нажать повторно, и без журнала повторное нажатие начисляло премиум заново.

    ``amount``/``currency`` — цена платежа в минорных единицах (XTR — звёзды,
    RUB — копейки, USDT — сотые): по журналу админка считает выручку. На
    начисление не влияют — только запись.

    Маркер платежа и начисление — в ОДНОЙ транзакции. Раньше маркер
    коммитился отдельно, до начисления, и падение процесса в зазоре оставляло
    платёж «зачтённым» навсегда без подписки: деньги списаны, а каждая
    повторная проверка отвечала «уже зачтено». Гонка двух одновременных
    проверок закрыта по-прежнему: маркер вставляется в savepoint, второй
    INSERT ждёт блокировку строки и падает на уникальном ключе, не начислив
    ничего. Так же устроен api/services/premium.py::activate_premium.
    """
    from datetime import timedelta

    from sqlalchemy.exc import IntegrityError

    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            if payment_id:
                try:
                    async with session.begin_nested():
                        session.add(
                            ProcessedPayment(
                                provider=provider,
                                external_id=payment_id,
                                user_id=user_id,
                                days=days,
                                amount=amount,
                                currency=currency,
                            )
                        )
                except IntegrityError:
                    # Savepoint откатился, внешняя транзакция жива — читаем
                    # текущую подписку, чтобы честно ответить, до когда она
                    result = await session.execute(
                        select(Subscription).where(Subscription.user_id == user_id)
                    )
                    sub = result.scalar_one_or_none()
                    return {
                        "plan": sub.plan if sub else "free",
                        "expires_at": sub.expires_at.isoformat() if sub and sub.expires_at else "",
                        "already_processed": True,
                    }

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

            # Воронка: props.provider отличает деньги (stars/cryptobot)
            # от бесплатных начислений — в той же транзакции, что подписка
            await _track_event_in(session, user_id, "purchase_completed", {
                "provider": provider, "tier": sub.plan, "days": days,
            })

            return {"plan": sub.plan, "expires_at": sub.expires_at.isoformat()}


async def activate_promo_code(user_id: str, raw_code: str) -> dict:
    """Активировать промокод — зеркало api/services/promo.py::activate_promo.

    Отказы возвращаются словарём {"activated": False, "reason": ...}, а не
    исключением: у бота нет get_session, который превратил бы исключение в
    ответ. Атомарность та же: слот лимита списывается одним UPDATE с
    проверкой остатка в WHERE, повторная активация одним человеком ловится
    уникальной парой (promo_id, user_id) — при гонке второй INSERT падает на
    ключе при коммите, IntegrityError откатывает транзакцию целиком, и
    списанный слот возвращается. Отказные ветки до записи возвращаются из
    session.begin() пустым коммитом — записать им нечего.

    Начисление подписки — в ТОЙ ЖЕ транзакции, что активация и слот
    (доктрина activate_premium: маркер и начисление коммитятся вместе).
    Сам activate_premium не зовём — он открывает собственную сессию, и
    между коммитами жил бы зазор: активация записана, подписка нет.
    """
    from datetime import timedelta

    from sqlalchemy.exc import IntegrityError

    код = raw_code.strip().upper().replace(" ", "").replace("-", "")
    if not код:
        return {"activated": False, "reason": "not_found"}

    cls = _session_cls()
    try:
        async with cls() as session:
            async with session.begin():
                промо = await session.scalar(
                    select(PromoCode).where(PromoCode.code == код)
                )
                # Погашенный код отвечает как несуществующий: подсказывать,
                # что утёкший код настоящий, незачем
                if not промо or not промо.is_active:
                    return {"activated": False, "reason": "not_found"}

                now = datetime.utcnow()
                if промо.expires_at and промо.expires_at.replace(tzinfo=None) < now:
                    return {"activated": False, "reason": "expired"}

                уже = await session.scalar(
                    select(PromoActivation).where(
                        and_(
                            PromoActivation.promo_id == промо.id,
                            PromoActivation.user_id == user_id,
                        )
                    )
                )
                if уже is not None:
                    return {"activated": False, "reason": "already_used"}

                списан = await session.execute(
                    update(PromoCode)
                    .where(
                        and_(
                            PromoCode.id == промо.id,
                            or_(
                                PromoCode.max_uses == 0,
                                PromoCode.used_count < PromoCode.max_uses,
                            ),
                        )
                    )
                    .values(used_count=PromoCode.used_count + 1)
                )
                if списан.rowcount == 0:
                    return {"activated": False, "reason": "exhausted"}

                session.add(PromoActivation(promo_id=промо.id, user_id=user_id))
                # Журнальный маркер — как у платежей, но amount=None:
                # промокод не выручка, метрики его не считают
                session.add(
                    ProcessedPayment(
                        provider="promo",
                        external_id=f"{промо.id}:{user_id}",
                        user_id=user_id,
                        days=промо.days,
                        amount=None,
                        currency=None,
                    )
                )

                result = await session.execute(
                    select(Subscription).where(Subscription.user_id == user_id)
                )
                sub = result.scalar_one_or_none()
                if not sub:
                    sub = Subscription(user_id=user_id)
                    session.add(sub)

                # Продление поверх остатка, уровень не понижаем — как в
                # activate_premium выше
                base = now
                if sub.expires_at:
                    current = sub.expires_at.replace(tzinfo=None)
                    if current > now:
                        base = current
                if tier_rank(промо.tier) >= tier_rank(sub.plan or "free"):
                    sub.plan = промо.tier
                sub.expires_at = base + timedelta(days=промо.days)
                await session.flush()

                # Воронка: promo — не выручка, отчёты отсекают по provider
                await _track_event_in(session, user_id, "purchase_completed", {
                    "provider": "promo", "tier": sub.plan, "days": промо.days,
                })

                logger.info(
                    f"promo activated: code={промо.code} tier={промо.tier} "
                    f"days={промо.days} user={user_id}"
                )
                return {
                    "activated": True,
                    "tier": промо.tier,
                    "days": промо.days,
                    "plan": sub.plan,
                    "expires_at": sub.expires_at.isoformat(),
                }
    except IntegrityError:
        # Гонка: два сообщения с одним кодом от одного человека. Второй
        # INSERT активации упал на uq_promo_activation при коммите, вся его
        # транзакция откатилась — слот и подписка целы
        return {"activated": False, "reason": "already_used"}


async def redeem_gift_code(user_id: str, raw_code: str) -> dict:
    """Активировать подарочный код — зеркало api/services/gifting.py::redeem_gift.

    Вызывается из FSM промокода: человек прислал код, activate_promo_code
    ответил not_found — пробуем прочитать ввод как подарочный код. Отказы
    возвращаются словарём {"redeemed": False, "reason": ...}, как у промо:
    у бота нет get_session, который превратил бы исключение в ответ. Отказ
    код НЕ сжигает — все отказные ветки возвращаются до UPDATE.

    Сжигание — одним UPDATE с `redeemed_at IS NULL` в WHERE: из двух
    одновременных активаций выигрывает ровно одна. Маркер журнала — тот же
    ключ ("gift", f"gift_{id}"), что пишет API: гонка «бот и мини-апп
    одним кодом» упирается в уникальную пару и тоже даёт одно начисление.
    Маркер и подписка — в одной транзакции (доктрина activate_premium).
    """
    from datetime import timedelta

    from sqlalchemy.exc import IntegrityError

    код = raw_code.strip().upper().replace(" ", "").replace("-", "")
    if not код:
        return {"redeemed": False, "reason": "not_found"}
    хеш = hashlib.sha256(код.encode()).hexdigest()

    cls = _session_cls()
    try:
        async with cls() as session:
            async with session.begin():
                gift = await session.scalar(
                    select(GiftSubscription).where(GiftSubscription.code_hash == хеш)
                )
                if not gift:
                    return {"redeemed": False, "reason": "not_found"}
                if not gift.paid:
                    return {"redeemed": False, "reason": "not_paid"}
                if gift.redeemed_at:
                    return {"redeemed": False, "reason": "already_used"}

                now = datetime.utcnow()
                if gift.expires_at and gift.expires_at.replace(tzinfo=None) < now:
                    return {"redeemed": False, "reason": "expired"}

                # Подарок ниже действующего уровня не активируем и не сжигаем:
                # иначе Plus-код молча сгорал бы у владельца Aurora. Равный
                # уровень — продление поверх остатка. Истёкшая подписка
                # уровнем не считается.
                result = await session.execute(
                    select(Subscription).where(Subscription.user_id == user_id)
                )
                sub = result.scalar_one_or_none()
                действующий = "free"
                if sub and (
                    sub.expires_at is None
                    or sub.expires_at.replace(tzinfo=None) > now
                ):
                    действующий = tier_from_plan(sub.plan)
                if tier_rank(действующий) > tier_rank(gift.plan):
                    return {"redeemed": False, "reason": "tier_lower"}

                сожжён = await session.execute(
                    update(GiftSubscription)
                    .where(and_(
                        GiftSubscription.id == gift.id,
                        GiftSubscription.redeemed_at.is_(None),
                    ))
                    .values(redeemed_at=now, recipient_user_id=user_id)
                )
                if сожжён.rowcount == 0:
                    return {"redeemed": False, "reason": "already_used"}

                # Журнальный маркер — как у платежей, но amount=None: деньги
                # за подарок уже учтены покупкой, активация не выручка
                session.add(
                    ProcessedPayment(
                        provider="gift",
                        external_id=f"gift_{gift.id}",
                        user_id=user_id,
                        days=gift.months * 30,
                        amount=None,
                        currency=None,
                    )
                )

                if not sub:
                    sub = Subscription(user_id=user_id)
                    session.add(sub)

                # Продление поверх остатка, уровень не понижаем — как в
                # activate_premium выше
                base = now
                if sub.expires_at:
                    current = sub.expires_at.replace(tzinfo=None)
                    if current > now:
                        base = current
                if tier_rank(gift.plan) >= tier_rank(sub.plan or "free"):
                    sub.plan = gift.plan
                sub.expires_at = base + timedelta(days=gift.months * 30)
                await session.flush()

                # Воронка: gift — не выручка, отчёты отсекают по provider
                await _track_event_in(session, user_id, "purchase_completed", {
                    "provider": "gift", "tier": sub.plan, "days": gift.months * 30,
                })

                logger.info(
                    f"gift redeemed via bot: plan={gift.plan} "
                    f"months={gift.months} user={user_id}"
                )
                return {
                    "redeemed": True,
                    "tier": gift.plan,
                    "months": gift.months,
                    "plan": sub.plan,
                    "expires_at": sub.expires_at.isoformat(),
                }
    except IntegrityError:
        # Гонка «бот и мини-апп одним кодом»: маркер упал на уникальной паре
        # (provider, external_id) при коммите, транзакция откатилась целиком —
        # начисление уже сделала другая сторона, код цел у неё
        return {"redeemed": False, "reason": "already_used"}


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
    upgraded — прежний pass заменён на лайк, limited — суточный лимит лайков
    исчерпан и лайк НЕ записан (см. services/quotas.py), likes_left — сколько
    лайков осталось после этого (None на платном уровне и на пропуске).
    """
    u1, u2 = (liker_id, liked_id) if liker_id < liked_id else (liked_id, liker_id)
    cls = _session_cls()
    async with cls() as session:
        async with session.begin():
            # Два лока, и всегда в этом порядке: сначала личный, потом парный.
            # Тот же порядок в api/routers/likes.py — обратный порядок в одном
            # из двух сервисов это классический дедлок: встречные лайк из бота
            # и лайк из мини-аппа упёрлись бы друг в друга насмерть.
            #
            # Личный нужен суточной квоте: она считается по всем целям сразу, и
            # парный ключ её не защищает — два одновременных лайка РАЗНЫМ людям
            # берут разные парные ключи, оба читают «использовано 9 из 10» и
            # оба проходят.
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": f"dating:likes:{liker_id}"},
            )
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": f"dating:pair:{u1}:{u2}"},
            )

            result = await session.execute(
                select(Like).where(Like.liker_id == liker_id, Like.liked_id == liked_id)
            )
            existing = result.scalar_one_or_none()

            # Суточный лимит — под тем же личным локом и с той же поправкой,
            # что в API: тратят его только НОВЫЕ лайки. Пропуск не тратит
            # ничего (иначе лимит запрещал бы листать деку), а повторный лайк
            # той же анкеты уже лежит в подсчёте — отказ по нему отобрал бы
            # израсходованное. Суперлайк тратит: это тоже лайк, просто с
            # отдельной квотой сверху.
            осталось: int | None = None
            if like_type != "pass" and (existing is None or existing.type == "pass"):
                лимит = await quotas.likes_state(session, liker_id)
                if лимит.exhausted:
                    # Ничего не записываем: лайка не было. Ключи matched/match
                    # оставляем на месте, чтобы вызывающий код без проверки
                    # `limited` падал не по KeyError, а просто не показывал мэтч
                    return {
                        "matched": False,
                        "match": None,
                        "upgraded": False,
                        "limited": True,
                        "limit": лимит.limit,
                        "reset_at": лимит.reset_at,
                    }
                if not лимит.unlimited:
                    # Остаток ПОСЛЕ этого лайка — считаем здесь, пока состояние
                    # под рукой: отдельный запрос из хендлера на каждую карточку
                    # означал бы лишний round-trip на каждый свайп
                    осталось = max(0, лимит.left - 1)

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
                return {
                    "matched": False,
                    "match": None,
                    "upgraded": upgraded,
                    "likes_left": осталось,
                }

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
                "likes_left": осталось,
                "match": {
                    "id": match.id,
                    "user1_id": match.user1_id,
                    "user2_id": match.user2_id,
                    "match_score": match.match_score,
                },
            }


def _возраст_из_даты(birth_date: datetime | None) -> int | None:
    """Полных лет по дате рождения. Копия `возраст_из_даты` из API.

    Считаем в UTC: дата рождения приходит и naive (из формы), и aware (из
    базы), а сравнивать их напрямую нельзя — падает на TypeError.
    Дублируется, потому что бот и API живут в разных venv и импортировать
    код друг друга не могут (см. api/services/public_profile.py).
    """
    if not birth_date:
        return None

    now = datetime.now(timezone.utc)
    if birth_date.tzinfo is None:
        birth_date = birth_date.replace(tzinfo=timezone.utc)

    возраст = now.year - birth_date.year
    if (now.month, now.day) < (birth_date.month, birth_date.day):
        возраст -= 1
    return возраст


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

        # Кого не показывать — анти-джойнами внутри запроса, а не списком id.
        # Раньше здесь вычитывались все лайки, все блокировки в обе стороны и
        # все чужие «пропустить», после чего уезжали обратно одним NOT IN. У
        # активного свайпера это десятки тысяч плейсхолдеров: план не
        # кэшируется, анти-джойн вырождается в Seq Scan по анкетам. Условия
        # дословно те же, что в api/services/matching.py.
        filters = [
            User.is_banned == False,
            # Инкогнито и пауза убирают из деки одинаково — см. api/models
            Profile.is_incognito == False,
            Profile.is_paused == False,
            Profile.display_name != "",  # пустые анкеты не показываем
            # Кому я уже поставил лайк или «пропустить»
            not_(
                select(Like.id)
                .where(and_(Like.liker_id == user_id, Like.liked_id == Profile.user_id))
                .exists()
            ),
            # Блокировки — в обе стороны, иначе жертва снова увидит обидчика
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
            # Кто поставил мне «пропустить» — взаимности уже не будет,
            # показывать их анкеты значит тратить деку впустую
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
            Profile.user_id != user_id,
        ]
        if my and my.looking_for and my.looking_for != "any":
            filters.append(Profile.gender.in_([my.looking_for, "other"]))

        # Возрастной диапазон — самый базовый фильтр дейтинга, и он задаётся
        # в мини-аппе. Без него человек выставил «25-30» в приложении, а бот
        # показывал всех подряд. Считаем по дате рождения: границы окна —
        # это «сегодня минус N лет».
        #
        # Анкеты без даты рождения НЕ отсеиваем. Сравнение в SQL с NULL даёт
        # NULL, то есть строка выпадала целиком — а `age_min`/`age_max` имеют
        # значения по умолчанию (18/99) и всегда истинны, так что фильтр
        # применялся ко всем. Человек без указанной даты просто исчезал из
        # деки бота, оставаясь видимым в мини-аппе (api/services/matching.py
        # фильтрует возраст в Python и такие анкеты сохраняет).
        if my and (my.age_min or my.age_max):
            if my.age_max:
                # Кто старше верхней границы — родился раньше этой даты
                filters.append(or_(
                    Profile.birth_date.is_(None),
                    Profile.birth_date >= _дата_рождения_для(my.age_max + 1),
                ))
            if my.age_min:
                filters.append(or_(
                    Profile.birth_date.is_(None),
                    Profile.birth_date <= _дата_рождения_для(my.age_min),
                ))

        # Обратная сторона того же фильтра: подхожу ли Я под ИХ диапазон.
        # В API это отдельная проверка (`my_age < profile.age_min`), и без
        # неё бот показывал бы 40-летнему анкеты тех, кто ищет 18-25.
        мой_возраст = _возраст_из_даты(my.birth_date) if my else None
        if мой_возраст:
            filters.append(Profile.age_min <= мой_возраст)
            filters.append(Profile.age_max >= мой_возраст)

        # Нишевые фильтры задаются в мини-аппе, а действовать должны и здесь:
        # иначе человек выставил «гот» в приложении, а бот показывает всех.
        # Анкеты с незаполненным полем не отсеиваем — они не виноваты, что
        # графа пустая, и иначе выдача схлопнулась бы почти до нуля.
        if my and my.filter_goal:
            filters.append(Profile.goal.in_([my.filter_goal, ""]))
        if my and my.filter_relation_type:
            filters.append(Profile.relation_type.in_([my.filter_relation_type, ""]))
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

        # «Только подтверждённые» — защитный фильтр, включается в мини-аппе
        # (см. api/models/models.py, почему он бесплатный). Запрос деки у бота
        # свой, а не общий с API, поэтому условие обязано повториться здесь:
        # иначе человек включил фильтр в приложении, а бот продолжает
        # показывать неподтверждённых — защита, которая действует только на
        # одной из двух поверхностей, хуже её отсутствия, потому что ей верят.
        # User уже в джойне (_scan тянет галочку тем же запросом).
        if my and my.filter_verified:
            filters.append(User.is_verified == True)

        # Выборка от случайной точки sample_key по индексу вместо
        # ORDER BY RANDOM(): тому нужна сортировка всей таблицы на каждый
        # показ анкеты. У конца диапазона строк не хватит — добираем
        # с начала, иначе анкеты с большим ключом видели бы полупустую деку.
        async def _scan(*extra) -> list[tuple[Profile, bool, datetime | None]]:
            # User и так в джойне — галочка и возраст аккаунта едут тем же
            # запросом, без N+1
            result = await session.execute(
                select(Profile, User.is_verified, User.created_at)
                .join(User, Profile.user_id == User.id)
                .where(*filters, *extra)
                .order_by(Profile.sample_key)
                .limit(limit * 3)
            )
            return [(p, bool(v), c) for p, v, c in result.all()]

        cut = random.random()
        rows = await _scan(Profile.sample_key >= cut)
        if len(rows) < limit * 3:
            rows += await _scan(Profile.sample_key < cut)

        # Буст новичка (PRD §2.4.5): доля свежести 0..1 у кандидатов моложе
        # суток. Та же механика, что в api/services/matching.py, — считается
        # на лету от User.created_at, в базу ничего не пишется
        свежесть_по_id: dict[str, float] = {}
        profiles = []
        for p, verified, created_at in rows[: limit * 3]:
            анкета = _profile_to_dict(p)
            анкета["is_verified"] = verified
            profiles.append(анкета)
            if created_at is not None:
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                часы = (datetime.now(timezone.utc) - created_at).total_seconds() / 3600
                доля = max(0.0, 1.0 - часы / 24.0)
                if доля > 0:
                    свежесть_по_id[p.user_id] = доля

        # Встречный фильтр + сортировка по общим интересам
        my_gender = my.gender if my else "other"
        my_interests = set(
            (my.interests if isinstance(my.interests, list) else []) if my else []
        )

        def _visible(p: dict) -> bool:
            lf = p.get("looking_for") or "any"
            return lf == "any" or lf == my_gender or my_gender == "other"

        profiles = [p for p in profiles if _visible(p)]

        def _ключ(p: dict) -> float:
            балл = float(len(my_interests & set(p.get("interests") or [])))
            доля = свежесть_по_id.get(p["user_id"], 0.0)
            if доля and p.get("photos"):
                # Буст новичка на шкале бота: дека здесь ранжируется штуками
                # общих интересов, полная свежесть весит как два совпадения —
                # новичок виден раньше, но три общих интереса его обгоняют.
                # Без фото буст не даётся: механика не разгоняет пустышки
                балл += 2.0 * доля
            return балл

        profiles.sort(key=_ключ, reverse=True)
        return profiles[:limit]


async def get_match_partner(
    match_id: str, user_id: str, spend: bool = False
) -> dict | None:
    """Get the other user in a match.

    Возвращает None, если мэтч не существует, разорван или user_id
    не является его участником (защита от подстановки чужого match_id).

    Суточный лимит открытых мэтчей (бесплатный уровень): у закрытого мэтча
    возвращаем маркер `{"locked": True, ...}` вместо анкеты. Вычищаем здесь, а
    не в хендлере: путей к партнёру четыре (открыть чат, отправить сообщение,
    подсказка, пуш о мэтче), и «замок только на кнопке» протекал бы в трёх
    оставшихся.

    `spend=True` — это ОТКРЫТИЕ мэтча, оно тратит суточный слот. По умолчанию
    False: проверка участия при отправке сообщения, подсказка и пуш о новом
    мэтче не должны сжигать квоту — иначе пришедшее сообщение молча съедало бы
    открытие, которого человек не делал.
    """
    cls = _session_cls()
    async with cls() as session:
        # Вся работа — одной транзакцией, открытой ДО первого запроса. Так
        # нужно из-за `open_match`: он берёт advisory-lock, а тот живёт до
        # конца транзакции, и без явного begin() автокоммит закрыл бы её сразу
        # после SELECT, оставив вставку без защиты.
        #
        # Открыть транзакцию позже нельзя: SQLAlchemy начинает её сама на
        # первом же запросе (autobegin), и `session.begin()` после SELECT
        # падает с InvalidRequestError «A transaction is already begun».
        # Здесь так и было — открытие чата с `spend=True` не работало вовсе.
        async with session.begin():
            result = await session.execute(
                select(Match).where(Match.id == match_id)
            )
            match = result.scalar_one_or_none()
            if not match or not match.is_active:
                return None
            if user_id not in (match.user1_id, match.user2_id):
                return None

            partner_id = match.user2_id if match.user1_id == user_id else match.user1_id

            if spend:
                итог = await quotas.open_match(session, user_id, match_id)
                if not итог.granted:
                    return _закрытый_мэтч(partner_id, итог.state)
            elif await quotas.match_locked(session, user_id, match_id):
                состояние = await quotas.match_views_state(session, user_id)
                return _закрытый_мэтч(partner_id, состояние)

    return await get_profile(partner_id)


def _закрытый_мэтч(partner_id: str, состояние) -> dict:
    """Мэтч за суточным лимитом: «есть кто-то», но не «вот кто».

    Ни имени, ни фото, ни города — ровно как `api/routers/matches.py` отдаёт
    закрытую строку списка. `user_id` оставляем: он нужен самому боту (кому
    слать, кого проверять), а человеку не показывается.
    """
    return {
        "locked": True,
        "user_id": partner_id,
        "limit": состояние.limit,
        "reset_at": состояние.reset_at,
    }


async def get_user_matches(user_id: str) -> list[dict]:
    """Мэтчи пользователя вместе с именами собеседников — одним запросом.

    Имя партнёра приходит джойном, а не отдельным `get_profile` на каждый
    мэтч. Раньше именно так и было в `handlers/matches.py`: список открывался
    циклом по мэтчам, и каждая итерация БРАЛА СВОЮ СЕССИЮ из пула бота (5
    постоянных плюс 10 сверх). У человека с полусотней мэтчей одно нажатие
    «Мои мэтчи» — это полсотни последовательных round-trip'ов к базе, и всё
    это время бот занят: aiogram обрабатывает апдейты в общем цикле.

    Кто из пары собеседник, решает CASE на стороне Postgres — иначе джойн
    пришлось бы делать по обоим столбцам и разбирать результат в Python.

    LEFT JOIN, а не INNER: анкета партнёра может быть не создана (регистрацию
    бросили на полпути), и такой мэтч всё равно должен остаться в списке —
    иначе чат просто исчезает из интерфейса, хотя он существует.

    Список отдаём целиком — он и есть витрина подписки, — но у закрытых
    суточным лимитом строк вычищаем имя. Показ списка квоту НЕ тратит: иначе
    один заход в «Мои мэтчи» сжигал бы все суточные открытия сразу.
    """
    партнёр = case(
        (Match.user1_id == user_id, Match.user2_id), else_=Match.user1_id
    )
    cls = _session_cls()
    async with cls() as session:
        result = await session.execute(
            select(
                Match.id,
                партнёр.label("partner_id"),
                Match.match_score,
                Match.ai_reason,
                Match.created_at,
                Profile.display_name,
            )
            .outerjoin(Profile, Profile.user_id == партнёр)
            .where(
                (Match.user1_id == user_id) | (Match.user2_id == user_id),
                Match.is_active == True,  # noqa: E712
            )
            .order_by(Match.created_at.desc())
        )
        строки = result.all()

        # Два запроса на весь список, а не по одному на строку: `match_locked`
        # в цикле означал бы 50 пар запросов на 50 мэтчей — ровно то, от чего
        # этот метод и избавлялся (см. выше).
        открытые = await quotas.opened_match_ids(session, user_id)
        лимит = await quotas.match_views_state(session, user_id)

        мэтчи = []
        for строка in строки:
            закрыт = лимит.exhausted and строка.id not in открытые
            мэтчи.append(
                {
                    "id": строка.id,
                    "partner_id": строка.partner_id,
                    "match_score": строка.match_score,
                    "ai_reason": строка.ai_reason,
                    "created_at": (
                        строка.created_at.isoformat() if строка.created_at else None
                    ),
                    # Имя закрытого не отдаём наружу вообще: скрыть его только
                    # в тексте кнопки значит всё равно передать его в процесс,
                    # где следующая правка его и напечатает
                    "partner_name": (
                        "Скрыто" if закрыт else (строка.display_name or "Аноним")
                    ),
                    "locked": закрыт,
                }
            )
        return мэтчи


# ════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════

async def get_daily_limits(user_id: str) -> dict:
    """Остатки суточных лимитов — для текстов бота.

    Обёртка над `services/quotas.py`, открывающая сессию: хендлеры не должны
    знать про сессии, а прямой импорт квот в каждый хендлер расползся бы по
    файлам вместе с ошибками в приведении времени.

    Возвращает `likes` и `matches` как `QuotaState` (см. services/quotas.py) —
    у них есть `left`, `limit`, `unlimited` и `reset_at`, — а также `tier` и
    флаг `free`.
    """
    cls = _session_cls()
    async with cls() as session:
        return await quotas.limits_summary(session, user_id)


def _user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "role": user.role,
        "is_banned": user.is_banned,
        "banned_until": user.banned_until.isoformat() if user.banned_until else None,
        "is_verified": user.is_verified,
        "locale": user.locale or "ru",
        "last_seen_at": user.last_seen_at.isoformat() if user.last_seen_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


def _profile_to_dict(profile: Profile) -> dict:
    photos = profile.photos if isinstance(profile.photos, list) else json.loads(profile.photos or "[]")
    videos = profile.videos if isinstance(profile.videos, list) else json.loads(profile.videos or "[]")
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
        "videos": videos,
        "interests": interests,
        "ai_bio": profile.ai_bio,
        "looking_for": profile.looking_for,
        "goal": profile.goal or "",
        "relation_type": profile.relation_type or "",
        "subculture": profile.subculture or "",
        "mbti": profile.mbti or "",
        "height_cm": profile.height_cm,
        # Наклейка из коллекции: в боте картинку не показать (это SVG в вебе),
        # поэтому в текстовой карточке она отмечается значком редкости —
        # см. texts.ЗНАЧОК_НАКЛЕЙКИ
        "sticker": profile.sticker or "",
        # Опорное фото верификации — служебное поле для _finish_registration
        # (решает, снимать ли галочку при смене фото); в карточках не рисуется
        "verified_photo": profile.verified_photo or "",
    }
