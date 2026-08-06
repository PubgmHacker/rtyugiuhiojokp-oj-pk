"""Раздел Таро: детерминированность раскладов и деградация без AI-ключа.

Тестируем поведение, а не устройство кода: одинаковый вход даёт одинаковый
результат, разный вход — разный (или хотя бы не гарантированно тот же), а
без ключа Zhipu ответ приходит заготовленным текстом, а не падает и не
пустой.
"""

from __future__ import annotations

from datetime import date

from services.tarot_deck import DECK, DISCLAIMER
from services.tarot_spreads import (
    compatibility_spread,
    day_card,
    interpretation_for,
    relationship_spread,
    three_card_spread,
)


def test_карта_дня_одинакова_для_одного_пользователя_и_даты():
    d = date(2026, 8, 6)
    первый = day_card("user-1", d)
    второй = day_card("user-1", d)
    assert первый[0].card.name == второй[0].card.name


def test_карта_дня_меняется_при_смене_даты():
    пользователь = "user-1"
    карты_за_разные_дни = {
        day_card(пользователь, date(2026, 1, day))[0].card.name for day in range(1, 29)
    }
    # На 22 карты колоды и 28 разных дат почти наверняка встретится больше
    # одного имени — если бы дата не влияла на выбор, множество состояло бы
    # из одного элемента.
    assert len(карты_за_разные_дни) > 1


def test_три_карты_различны_внутри_одного_расклада():
    расклад = three_card_spread("user-42", date(2026, 8, 6))
    имена = [позиция.card.name for позиция in расклад]
    assert len(set(имена)) == len(имена)


def test_расклад_на_отношения_состоит_из_четырёх_разных_карт():
    расклад = relationship_spread("user-7", date(2026, 8, 6))
    assert len(расклад) == 4
    имена = [позиция.card.name for позиция in расклад]
    assert len(set(имена)) == 4


def test_расклад_он_и_я_одинаков_для_тех_же_имён_и_даты():
    d = date(2026, 8, 6)
    первый = compatibility_spread("Аня", "Игорь", d)
    второй = compatibility_spread("Аня", "Игорь", d)
    assert [p.card.name for p in первый] == [p.card.name for p in второй]


def test_расклад_он_и_я_не_зависит_от_пробелов_и_регистра_имени():
    d = date(2026, 8, 6)
    ровно = compatibility_spread("Аня", "Игорь", d)
    с_пробелами = compatibility_spread(" АНЯ ", " игорь ", d)
    assert [p.card.name for p in ровно] == [p.card.name for p in с_пробелами]


def test_расклад_он_и_я_меняется_при_других_именах():
    d = date(2026, 8, 6)
    пара_1 = compatibility_spread("Аня", "Игорь", d)
    пара_2 = compatibility_spread("Мария", "Пётр", d)
    assert [p.card.name for p in пара_1] != [p.card.name for p in пара_2]


def test_все_карты_расклада_из_общей_колоды():
    расклад = day_card("user-1", date(2026, 8, 6))
    имена_колоды = {card.name for card in DECK}
    assert расклад[0].card.name in имена_колоды


async def test_без_ключа_zhipu_интерпретация_это_заготовка_а_не_ошибка(monkeypatch):
    import services.ai_moderation as ai_moderation

    monkeypatch.setattr(ai_moderation, "_get_zhipu_client", lambda: None)

    расклад = three_card_spread("user-1", date(2026, 8, 6))
    текст = await interpretation_for("three", расклад)

    assert текст  # не пусто и не падает исключением
    # Заготовка собрана из советов по картам — значит это не случайный текст,
    # а осмысленный fallback
    assert расклад[0].card.advice in текст


def test_дисклеймер_есть_в_общем_тексте():
    assert "развлечение" in DISCLAIMER.lower()
    assert "предсказание" in DISCLAIMER.lower()
