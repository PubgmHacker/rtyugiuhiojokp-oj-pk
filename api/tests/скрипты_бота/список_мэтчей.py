"""Список мэтчей бота: одним запросом и с именами — на настоящей БД в памяти.

Форму SQL проверить мало: `get_user_matches` может вернуть верные строки и
всё равно уйти в N+1, если имена собирает вызывающий. Раньше так и было —
`handlers/matches.py` шёл циклом по мэтчам и на каждый звал `get_profile`,
а тот брал СВОЮ сессию из пула бота (5 постоянных плюс 10 сверх). Полсотни
мэтчей — полсотни последовательных round-trip'ов в общем цикле aiogram.

Поэтому здесь считаются реальные обращения к базе через `before_cursor_execute`
и проверяется, что имя партнёра пришло вместе с мэтчем.

Запускается интерпретатором бота из `tests/test_query_scale.py`.
Ответ — JSON на последней строке stdout.
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import database.connection as c
from database.models import Match, Profile, User

#: Сколько мэтчей заводим. Число нарочно больше пары: при N+1 счётчик
#: запросов растёт вместе с ним, при джойне остаётся единицей.
СКОЛЬКО = 12


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(User.metadata.create_all)

    session_cls = async_sessionmaker(engine, expire_on_commit=False)
    c._session_cls = lambda: session_cls

    async with session_cls() as session:
        session.add(User(id="U0", telegram_id=100))
        session.add(Profile(user_id="U0", display_name="Я", gender="male"))
        for i in range(1, СКОЛЬКО + 1):
            uid = f"U{i}"
            session.add(User(id=uid, telegram_id=100 + i))
            session.add(Profile(user_id=uid, display_name=f"Партнёр {i}", gender="female"))
            # Пара нормализована (u1 < u2), как её пишет API, и половину
            # мэтчей заводим «наоборот» — я должен оказаться то первым, то
            # вторым участником, иначе CASE проверялся бы только с одной
            # стороны
            первый, второй = ("U0", uid) if i % 2 else (uid, "U0")
            session.add(Match(
                id=f"M{i}", user1_id=первый, user2_id=второй,
                is_active=True, match_score=50 + i,
                created_at=datetime(2026, 1, 1) + timedelta(minutes=i),
            ))
        # Мэтч с человеком без анкеты: регистрацию бросили на полпути.
        # INNER JOIN выкинул бы эту беседу из списка — чат существует, а в
        # интерфейсе его нет
        session.add(User(id="U99", telegram_id=199))
        session.add(Match(
            id="M99", user1_id="U0", user2_id="U99", is_active=True,
            created_at=datetime(2026, 1, 1),
        ))
        # Разведённая пара — в списке ей не место
        session.add(User(id="U88", telegram_id=188))
        session.add(Profile(user_id="U88", display_name="Бывший мэтч", gender="female"))
        session.add(Match(
            id="M88", user1_id="U0", user2_id="U88", is_active=False,
            created_at=datetime(2026, 1, 1),
        ))
        await session.commit()

    # Считаем обращения к базе только на самом вызове — вставки выше не в счёт
    запросы: list[str] = []

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def _считать(conn, cursor, statement, parameters, context, executemany):
        запросы.append(statement)

    мэтчи = await c.get_user_matches("U0")

    имена = {м["id"]: м.get("partner_name") for м in мэтчи}
    партнёры = {м["id"]: м["partner_id"] for м in мэтчи}

    print(json.dumps({
        "запросов": len(запросы),
        "мэтчей": len(мэтчи),
        # Ключи есть у всех, и ни один не пустой: «Аноним» для брошенной
        # анкеты — тоже имя
        "все_с_именами": all(м.get("partner_name") for м in мэтчи),
        "имя_первого_мэтча": имена.get("M1"),
        # Я — user2 в этой паре, партнёр должен вычислиться в обратную сторону
        "имя_обратной_пары": имена.get("M2"),
        "партнёр_обратной_пары": партнёры.get("M2"),
        "без_анкеты_в_списке": "M99" in имена,
        "имя_без_анкеты": имена.get("M99"),
        "разведённый_в_списке": "M88" in имена,
        # Свежие сверху — список открывается ради последних бесед
        "порядок_по_убыванию": [м["id"] for м in мэтчи][:3],
        "себя_в_партнёрах_нет": "U0" not in партнёры.values(),
    }, ensure_ascii=False))

    await engine.dispose()


asyncio.run(main())
