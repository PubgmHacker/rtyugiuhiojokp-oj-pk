from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

import aiohttp

from config import CRYPTOBOT_TOKEN

logger = logging.getLogger(__name__)

API_BASE = "https://pay.crypt.bot/api"


def is_enabled() -> bool:
    return bool(CRYPTOBOT_TOKEN)


async def _call(method: str, payload: dict | None = None) -> dict | None:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{API_BASE}/{method}",
                json=payload or {},
                headers={"Crypto-Pay-API-Token": CRYPTOBOT_TOKEN},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.error(f"CryptoBot {method} error: {data}")
                    return None
                return data.get("result")
    except Exception as e:
        logger.error(f"CryptoBot {method} failed: {e}")
        return None


async def create_premium_invoice(
    user_id: str, amount: str, title: str = "Симп Premium", plan_code: str = "",
) -> dict | None:
    """Создать счёт в USDT. Возвращает {'invoice_id': int, 'url': str} или None.

    Сумма приходит из тарифной линейки, а не из настроек: тарифов теперь
    несколько, и общая цена для всех означала бы, что годовой Ultra стоит
    столько же, сколько месяц Plus.

    Код тарифа зашивается в payload: проверка оплаты сверяет его с тем, что
    пользователь предъявил в callback_data. Без этого тариф определяла бы
    только подделываемая кнопка — оплатил дешёвый, предъявил код дорогого.
    """
    result = await _call("createInvoice", {
        "asset": "USDT",
        "amount": str(amount),
        "description": title,
        "payload": f"premium:{user_id}:{plan_code}" if plan_code else f"premium:{user_id}",
        "expires_in": 3600,
    })
    if not result:
        return None
    return {
        "invoice_id": result["invoice_id"],
        "url": result.get("bot_invoice_url") or result.get("pay_url", ""),
    }


async def check_invoice_paid(
    invoice_id: int,
    expected_user_id: str,
    plan_code: str = "",
    expected_amount: str = "",
) -> bool:
    """Проверить статус счёта (кнопка «Проверить оплату»).

    Сверяем не только «оплачен», но ЧЕЙ счёт и ЗА ЧТО: callback_data
    подделывается клиентом, а invoice_id последовательные. Без проверки
    владельца чужой оплаченный счёт активировал бы премиум атакующему.
    Без проверки тарифа хватало оплатить самый дешёвый тариф и нажать
    «Проверить оплату» с подставленным кодом дорогого — начислялся он.

    Тариф подтверждает код в payload (новые счета). Счета без кода — созданные
    до того, как код стал зашиваться, они живут не дольше часа после деплоя —
    подтверждаются суммой: цены тарифов попарно различны, и сумма однозначно
    определяет купленное.
    """
    result = await _call("getInvoices", {"invoice_ids": str(invoice_id)})
    if not result:
        return False
    items = result.get("items") or []
    if not items:
        return False
    inv = items[0]
    if inv.get("status") != "paid":
        return False

    payload = inv.get("payload") or ""
    if plan_code and payload == f"premium:{expected_user_id}:{plan_code}":
        return True

    if payload == f"premium:{expected_user_id}":
        # Переходный формат без кода тарифа — подтверждаем суммой и валютой
        if inv.get("asset") != "USDT" or not expected_amount:
            return False
        try:
            return Decimal(str(inv.get("amount"))) == Decimal(expected_amount)
        except (InvalidOperation, TypeError):
            return False

    return False
