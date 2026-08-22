"""Промокоды на подписку.

Маркетинговый инструмент: админка выпускает код с тарифом, сроком и лимитом
активаций, пользователь вводит его в боте или мини-аппе и получает подписку
бесплатно. Этим промокод отличается от подарочного кода (services/gifting.py):
подарок оплачен и одноразов, промокод бесплатен и многоразов — один код на
max_uses разных людей, но каждый человек активирует его только один раз.

Атомарность активации:
- слот лимита списывается одним UPDATE с проверкой остатка прямо в WHERE —
  две одновременные активации не перепродадут последний слот: у второй
  rowcount будет 0;
- повторная активация тем же человеком ловится уникальной парой
  (promo_id, user_id) — при гонке второй INSERT падает на ключе;
- начисление идёт через activate_premium в ТОЙ ЖЕ сессии: маркер
  ProcessedPayment("promo", ...) и подписка коммитятся вместе со слотом
  и активацией. Любой отказ — исключение PromoError, транзакцию запроса
  откатывает get_session, и списанный слот возвращается.

В выручку админки промокоды не попадают: activate_premium зовётся с
amount=None — метрики считают только строки с суммой.
"""
from __future__ import annotations

import logging
import secrets

from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import PromoActivation, PromoCode
from services.premium import activate_premium
from services.public_profile import в_utc

logger = logging.getLogger(__name__)

#: Алфавит без похожих знаков (0/O, 1/I) — код диктуют голосом и
#: перепечатывают с картинок. Тот же, что у подарочных кодов.
_АЛФАВИТ = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

#: 8 знаков из 32 — триллион вариантов: перебор непрактичен, а в посте или
#: на сторис код остаётся коротким. Подарочный код длиннее (12), потому что
#: он — платёжный секрет; промокод — публичный.
CODE_LEN = 8

#: Каким может быть кастомный код из админки: только наш алфавит плюс 0/1/I/O
#: (человеческие коды вроде «HELLO2026» законны), без пробелов и знаков.
_ДОПУСТИМЫЙ_КОД = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
MIN_CODE_LEN = 4
MAX_CODE_LEN = 32


class PromoError(Exception):
    """Отказ активации. reason — машинный код для клиента, text — человеку.

    Поднимается исключением, а не возвращается словарём, намеренно: роутер
    превратит его в HTTPException, get_session откатит транзакцию, и ни одна
    отказная ветка не оставит в базе следов (в том числе списанного слота).
    """

    def __init__(self, reason: str, text: str) -> None:
        super().__init__(text)
        self.reason = reason
        self.text = text


def normalize_code(raw: str) -> str:
    """Верхний регистр, без пробелов и дефисов: человек копирует код из
    поста с «SIMP-2026» или вводит «simp 2026» — это один и тот же код."""
    return raw.strip().upper().replace(" ", "").replace("-", "")


def generate_promo_code() -> str:
    """Сгенерировать код. secrets, а не random: код с ненулевой ценой."""
    return "".join(secrets.choice(_АЛФАВИТ) for _ in range(CODE_LEN))


def валидный_кастомный_код(код: str) -> bool:
    """Проверка кода, введённого админом руками (уже нормализованного)."""
    return (
        MIN_CODE_LEN <= len(код) <= MAX_CODE_LEN
        and all(символ in _ДОПУСТИМЫЙ_КОД for символ in код)
    )


async def activate_promo(session: AsyncSession, user_id: str, raw_code: str) -> dict:
    """Активировать промокод. Возвращает данные новой подписки,
    любой отказ — PromoError.

    Порядок проверок — от понятного человеку к тонкому: код существует →
    код не просрочен → ты его ещё не использовал → в нём остались слоты.
    Выключенный админом код отвечает «не найден», как и несуществующий:
    погашенный после утечки код не должен подтверждать, что он настоящий.
    """
    код = normalize_code(raw_code)
    if not код:
        raise PromoError("not_found", "Такого промокода нет")

    промо = await session.scalar(select(PromoCode).where(PromoCode.code == код))
    if not промо or not промо.is_active:
        raise PromoError("not_found", "Такого промокода нет")

    if промо.expires_at and в_utc(промо.expires_at) < datetime.now(timezone.utc):
        raise PromoError("expired", "Срок действия промокода истёк")

    уже = await session.scalar(
        select(PromoActivation).where(
            PromoActivation.promo_id == промо.id,
            PromoActivation.user_id == user_id,
        )
    )
    if уже is not None:
        raise PromoError("already_used", "Вы уже активировали этот промокод")

    # Слот списывается атомарно: остаток проверяет сам UPDATE. Ветка отказа
    # ничего не записала, а ветка успеха ниже либо дойдёт до коммита целиком,
    # либо PromoError откатит транзакцию вместе со слотом.
    списан = await session.execute(
        update(PromoCode)
        .where(
            PromoCode.id == промо.id,
            or_(PromoCode.max_uses == 0, PromoCode.used_count < PromoCode.max_uses),
        )
        .values(used_count=PromoCode.used_count + 1)
    )
    if списан.rowcount == 0:
        raise PromoError("exhausted", "Промокод уже закончился")

    try:
        # savepoint: при гонке двух активаций одним человеком второй INSERT
        # падает на uq_promo_activation, сессия остаётся рабочей, а PromoError
        # откатывает транзакцию целиком — вместе со списанным слотом
        async with session.begin_nested():
            session.add(PromoActivation(promo_id=промо.id, user_id=user_id))
    except IntegrityError:
        raise PromoError("already_used", "Вы уже активировали этот промокод")

    # Начисление — тем же путём, что платежи: продление поверх остатка,
    # уровень не понижается, идемпотентный маркер. amount=None — промокод
    # не выручка
    итог = await activate_premium(
        session,
        user_id=user_id,
        days=промо.days,
        payment_id=f"{промо.id}:{user_id}",
        provider="promo",
        tier=промо.tier,
        amount=None,
        currency=None,
    )

    logger.info(
        "promo activated: code=%s tier=%s days=%s user=%s",
        промо.code, промо.tier, промо.days, user_id,
    )
    return {
        "tier": промо.tier,
        "days": промо.days,
        "plan": итог["plan"],
        "expires_at": итог["expires_at"],
    }
