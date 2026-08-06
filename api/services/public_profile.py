"""Возраст в чужой анкете: один расчёт и один учёт настройки «скрыть возраст».

Формула возраста была скопирована в девять мест, и `hide_age` учитывался не во
всех: аудит уже ловил утечку в лайках, чатах и «Гостях», а после починки
осталась пятая копия в видео-ленте — там возраст отдавался мимо настройки.
Это ровно тот сорт расхождения, из-за которого в проекте появился
`chat_delivery.py`: правильный код есть, но ровно в одной копии.

Поэтому здесь две функции с разными обязанностями, и выбор между ними — это
явное решение о приватности, а не случайность:

- `возраст_из_даты` — просто арифметика, без всякой приватности. Годится там,
  где анкета своя (человек всегда видит свой возраст) и в админке.
- `публичный_возраст` — для ЛЮБОГО ответа, где анкету видит кто-то другой.
  Уважает `hide_age` и не требует от вызывающего помнить про флаг.

Если добавляете новое место, где отдаётся чужая анкета, берите
`публичный_возраст`. Тогда следующая настройка приватности добавится здесь
один раз, а не в девяти файлах.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def возраст_из_даты(birth_date: Optional[datetime]) -> Optional[int]:
    """Полных лет по дате рождения. Без учёта настроек приватности.

    Считаем в UTC: сравнение naive- и aware-даты падает, а дата рождения
    приходит и той, и другой (из формы — naive, из базы — aware).
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


def публичный_возраст(profile: Any) -> Optional[int]:
    """Возраст для показа другому человеку: `None`, если он его скрыл.

    Принимает анкету целиком, а не дату: тогда вызывающий не может забыть
    проверить `hide_age` — именно так и возникали утечки.
    """
    if profile is None:
        return None
    if getattr(profile, "hide_age", False):
        return None
    return возраст_из_даты(getattr(profile, "birth_date", None))


def наша_картинка(url: Optional[str]) -> bool:
    """Лежит ли картинка в нашем хранилище.

    Всё, что показывается людям, обязано пройти загрузку: там AI-модерация и
    срезание EXIF с координатами. Ссылка на чужой хост означает и необойдённую
    модерацию, и утечку IP получателя на посторонний сервер в момент показа.

    Пустое значение — не картинка, и это не ошибка: проверять нечего.
    """
    if not url:
        return True

    from config import get_settings

    prefix = (get_settings().R2_PUBLIC_URL or "").rstrip("/") + "/"
    if prefix != "/" and url.startswith(prefix):
        return True
    # Не ссылка вовсе — это file_id Telegram, его кладёт бот без R2
    return "://" not in url


def в_utc(момент: Optional[datetime]) -> Optional[datetime]:
    """Привести время из базы к aware-виду.

    Postgres с `timezone=True` отдаёт aware-время, а SQLite и старые записи —
    naive. Сравнение naive и aware падает с TypeError прямо в обработчике
    запроса: так ломалось начисление буста из кейса. Сравнивать время из БД
    напрямую с `datetime.now(timezone.utc)` нельзя — только через это.
    """
    if момент is None:
        return None
    if момент.tzinfo is None:
        return момент.replace(tzinfo=timezone.utc)
    return момент


def буст_активен(момент: Optional[datetime]) -> bool:
    """Действует ли буст прямо сейчас."""
    момент = в_utc(момент)
    return bool(момент and момент > datetime.now(timezone.utc))
