from __future__ import annotations

import logging

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger(__name__)


class BanGateMiddleware(BaseMiddleware):
    """Забаненный не пользуется ботом: любой апдейт отвечает экраном бана.

    До этого гейта бан жил только в API: мини-апп получал 403 и экран
    «Доступ закрыт», а бот продолжал работать как ни в чём не бывало —
    свайпы, мэтчи, переписка. Для бана за чужие фото это дыра в самой сути
    наказания.

    Пропускаем без гейта ровно то, чем бан снимается:
    * кнопку оплаты досрочной разблокировки (unban:pay);
    * successful_payment / refunded_payment — зачёт и возврат оплаты;
    * pre_checkout_query сюда не попадает вовсе: middleware висит только на
      message и callback_query (bot.py), подтверждение оплаты не блокируется.

    Ставится ПОСЛЕ RegistrationMiddleware: та кладёт db_user в data, и гейт
    не ходит в базу сам. Нет db_user (сбой регистрации) — пропускаем:
    жёсткая стена — проверка is_banned в API на каждом запросе, гейт же
    отвечает за честный интерфейс.
    """

    async def __call__(self, handler, event: TelegramObject, data: dict):
        db_user = data.get("db_user")
        if not db_user or not db_user.get("is_banned"):
            return await handler(event, data)

        if isinstance(event, Message) and (
            event.successful_payment or event.refunded_payment
        ):
            return await handler(event, data)

        from config import UNBAN_PRICE_RUB
        from keyboards import unban_kb
        import texts as T

        target: Message | None = event if isinstance(event, Message) else None
        if isinstance(event, CallbackQuery):
            if (event.data or "") == "unban:pay":
                return await handler(event, data)
            try:
                # Иначе на кнопке висели бы «часики»
                await event.answer("Аккаунт заблокирован")
            except Exception:
                pass
            # message бывает недоступным (InaccessibleMessage) — у него нет answer
            if isinstance(event.message, Message):
                target = event.message

        if target is not None:
            try:
                await target.answer(
                    T.ban_notice(
                        UNBAN_PRICE_RUB, until_iso=db_user.get("banned_until")
                    ),
                    reply_markup=unban_kb(UNBAN_PRICE_RUB),
                )
            except Exception as e:
                logger.warning(f"Не удалось показать экран бана: {e}")
        return None
