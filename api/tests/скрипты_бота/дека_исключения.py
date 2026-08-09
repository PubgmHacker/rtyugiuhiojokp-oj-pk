"""Кого дека БОТА реально исключает — на настоящей БД в памяти.

Форму SQL проверяет `test_дека_бота_тоже_без_списка_id`. Её недостаточно:
мутация «блокировки только в одну сторону» сохраняет и число анти-джойнов,
и корреляции, а жертва харассмента снова видит обидчика. Поэтому здесь дека
запускается целиком и проверяется состав выдачи.

Запускается интерпретатором бота из `tests/test_query_scale.py`.
Ответ — JSON на последней строке stdout.
"""

import asyncio
import json
import sys
from datetime import datetime

sys.path.insert(0, ".")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import database.connection as c
from database.models import Block, Like, Profile, User

#: Пятеро: я и по одному кандидату на каждое условие исключения.
#: U3 — контроль: если выпадет и он, тест поймает «дека вообще пуста»
#: вместо «условие работает».
УЧАСТНИКИ = (
    ("U1", "Я"),
    ("U2", "Заблокировавший меня"),
    ("U3", "Чистый"),
    ("U4", "Кого я лайкнул"),
    ("U5", "Кто меня пропустил"),
)


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(User.metadata.create_all)

    session_cls = async_sessionmaker(engine, expire_on_commit=False)
    c._session_cls = lambda: session_cls

    async with session_cls() as session:
        for uid, имя in УЧАСТНИКИ:
            session.add(User(id=uid, telegram_id=int(uid[1:])))
            session.add(Profile(
                user_id=uid, display_name=имя, gender="male",
                looking_for="any", age_min=18, age_max=99, sample_key=0.5,
                # Дата рождения обязательна: дека бота фильтрует возраст
                # прямо в SQL, и анкета без birth_date выпадает целиком
                birth_date=datetime(1995, 6, 15),
            ))
        # Анкета без даты рождения: в API она остаётся в деке (возраст там
        # фильтруется в Python), а в SQL-сравнении NULL давал NULL и строка
        # выпадала. Человек просто исчезал из бота, оставаясь в мини-аппе.
        session.add(User(id="U6", telegram_id=6))
        session.add(Profile(
            user_id="U6", display_name="Без даты рождения", gender="male",
            looking_for="any", age_min=18, age_max=99, sample_key=0.5,
            birth_date=None,
        ))
        # Ищет 18-25, а мне 31 — я не подхожу под ЕГО диапазон. В API это
        # отдельная проверка, в боте её не было вовсе.
        session.add(User(id="U7", telegram_id=7))
        session.add(Profile(
            user_id="U7", display_name="Ищет молодых", gender="male",
            looking_for="any", age_min=18, age_max=25, sample_key=0.5,
            birth_date=datetime(1996, 3, 10),
        ))
        # Обратная сторона блокировки: заблокировал ОН меня
        session.add(Block(id="B1", blocker_id="U2", blocked_id="U1"))
        # Мой собственный лайк
        session.add(Like(id="L1", liker_id="U1", liked_id="U4", type="like"))
        # Чужое «пропустить» в мою сторону
        session.add(Like(id="L2", liker_id="U5", liked_id="U1", type="pass"))
        await session.commit()

    дека = await c.get_deck_profiles("U1", limit=10)
    ids = sorted(анкета["user_id"] for анкета in дека)

    print(json.dumps({
        "ids": ids,
        "сам_себя": "U1" in ids,
        "заблокировавший_меня": "U2" in ids,
        "чистый_виден": "U3" in ids,
        "кого_лайкнул": "U4" in ids,
        "кто_пропустил_меня": "U5" in ids,
        "без_даты_рождения_виден": "U6" in ids,
        "ищет_молодых_виден": "U7" in ids,
    }, ensure_ascii=False))

    await engine.dispose()


asyncio.run(main())
