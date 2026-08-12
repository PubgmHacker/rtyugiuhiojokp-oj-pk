#!/usr/bin/env python3
"""Демо-данные для локальной разработки и review-аккаунта App Store.

Пустая база — худший способ смотреть на дейтинг: дека пустая, чаты
пустые, все экраны показывают empty-state, и оценить продукт глазами
пользователя невозможно. Инструмент наполняет базу правдоподобной
жизнью: анкеты с фото, входящие лайки, мэтчи с перепиской, истории,
серия общения, задачи на день, наклейки.

Фото — абстрактные градиентные карточки, сгенерированные локально
(PIL). Сознательно НЕ фотографии людей: чужие лица в демо-данных — это
и юридический риск, и обман глаз. Кладутся в web/public/demo-photos/ и
отдаются самим фронтендом, поэтому работают и на dev-сервере (5173), и
в предпросмотре (4180) без внешней сети и без R2.

Всё демо помечено `phone = "demo:NN"` — повторный запуск сначала сносит
прежних демо-пользователей (каскадом БД), потом создаёт заново.
Настоящие аккаунты инструмент не трогает.

Запуск:
    python3 tools/seed_demo.py                     # 12 анкет + жизнь вокруг dev:audit-jax
    python3 tools/seed_demo.py --me dev:my-device  # обвесить другой dev-аккаунт
    python3 tools/seed_demo.py --wipe              # только удалить демо-данные
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(КОРЕНЬ / "api"))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

log = logging.getLogger("seed_demo")

ФОТО_ПАПКА = КОРЕНЬ / "web" / "public" / "demo-photos"

#: Имя, пол, возраст, город, био, интересы, цель, тип связи, субкультура,
#: MBTI, рост. Люди разные нарочно: дека должна показать разброс бейджей.
ЛЮДИ = [
    ("Алиса", "female", 24, "Москва", "Кофе по утрам, плёночные камеры и виниловые пластинки. Ищу того, с кем можно молчать.", ["кофе", "фотография", "винил"], "relationship", "partner", "", "INFJ", 168),
    ("Мария", "female", 27, "Санкт-Петербург", "Танцую хастл, читаю Бродского вслух. Верю, что лучшие разговоры случаются на кухне.", ["танцы", "поэзия", "кино"], "dates", "", "", "ENFP", 172),
    ("Кира", "female", 22, "Москва", "Учусь на геймдизайнера. Могу пройти соулслайк без смертей, а вот мимо котика пройти не могу.", ["игры", "аниме", "котики"], "chat", "friends", "gamer", "INTP", 160),
    ("Соня", "female", 25, "Казань", "Пеку хлеб на закваске и бегаю полумарафоны. Противоречие? Возможно.", ["выпечка", "бег", "путешествия"], "relationship", "partner", "", "ISFJ", 165),
    ("Ева", "female", 29, "Москва", "Арт-директор. Люблю выставки, на которых ничего не понятно, и людей, которые не боятся это признать.", ["искусство", "дизайн", "вино"], "dates", "", "alt", "ENTJ", 175),
    ("Лера", "female", 23, "Новосибирск", "Играю на барабанах в группе, о которой ты не слышал. Пока.", ["музыка", "концерты", "татуировки"], "chat", "girlfriends", "punk", "ESFP", 163),
    ("Марк", "male", 28, "Москва", "Пишу бэкенды днём и музыку ночью. Настоящий стек: синтезаторы и кофе.", ["музыка", "код", "кофе"], "relationship", "partner", "", "INTJ", 183),
    ("Даня", "male", 25, "Санкт-Петербург", "Скейт, стрит-фото и рамен. Покажу лучшие споты города.", ["скейт", "фотография", "рамен"], "chat", "friends", "skate", "ENFP", 178),
    ("Артём", "male", 31, "Москва", "Горы зимой, вейк летом. Между сезонами — шахматы и бокс.", ["сноуборд", "шахматы", "бокс"], "dates", "", "", "ESTJ", 186),
    ("Илья", "male", 26, "Екатеринбург", "Варю кофе как бариста, спорю как юрист. Первое — профессия, второе — хобби.", ["кофе", "стендап", "книги"], "relationship", "partner", "", "ENTP", 180),
    ("Кирилл", "male", 24, "Москва", "Гоняю в доту и на велосипеде. В обоих случаях — за команду.", ["игры", "велосипед", "мемы"], "chat", "friends", "gamer", "ISTP", 176),
    ("Никита", "male", 29, "Санкт-Петербург", "Реставрирую мебель и старые фильмы вкусов. Могу отличить тик от дуба с закрытыми глазами.", ["кино", "дерево", "джаз"], "dates", "", "casual", "ISFP", 181),
]

#: Пары оттенков (тёмный, светлый) для градиентных «портретов». Разные
#: люди — разные карточки; повторяются только после двенадцатой.
ПАЛИТРЫ = [
    ((36, 12, 40), (255, 96, 130)), ((10, 28, 52), (96, 160, 255)),
    ((44, 20, 10), (255, 160, 90)), ((12, 40, 32), (80, 220, 170)),
    ((40, 12, 24), (255, 120, 190)), ((24, 16, 48), (150, 120, 255)),
    ((8, 32, 44), (90, 200, 230)), ((44, 32, 10), (250, 200, 90)),
    ((30, 10, 44), (200, 110, 255)), ((10, 36, 20), (120, 230, 130)),
    ((44, 10, 14), (255, 110, 100)), ((14, 22, 46), (130, 150, 255)),
]

КООРДИНАТЫ = {
    "Москва": (55.7558, 37.6173),
    "Санкт-Петербург": (59.9343, 30.3351),
    "Казань": (55.7963, 49.1088),
    "Новосибирск": (55.0084, 82.9357),
    "Екатеринбург": (56.8389, 60.6057),
}


def _портрет(индекс: int, вариант: int) -> str:
    """Нарисовать градиентную карточку 900×1200 и вернуть относительный URL.

    Абстракция, а не лицо: три размытых пятна аналогичных оттенков на
    тёмной базе. Поверх таких карточек дека кладёт имя и бейджи — по
    контрасту это ближе к реальному фото, чем плоская заглушка.
    """
    ш, в = 900, 1200
    тёмный, светлый = ПАЛИТРЫ[индекс % len(ПАЛИТРЫ)]
    rnd = random.Random(индекс * 100 + вариант)

    img = Image.new("RGB", (ш, в), тёмный)
    d = ImageDraw.Draw(img)

    for _ in range(3):
        r = rnd.randint(260, 480)
        cx, cy = rnd.randint(0, ш), rnd.randint(0, в)
        t = rnd.uniform(0.35, 0.9)
        цвет = tuple(
            int(тёмный[i] + (светлый[i] - тёмный[i]) * t) for i in range(3)
        )
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=цвет)

    img = img.filter(ImageFilter.GaussianBlur(160))

    # Виньетка снизу, как затемнение под текст в деке: на снимке без неё
    # белая подпись имени тонет на светлом пятне.
    тень = Image.new("L", (ш, в), 0)
    ImageDraw.Draw(тень).polygon([(0, в), (ш, в), (ш, int(в * 0.55)), (0, int(в * 0.55))], fill=90)
    тень = тень.filter(ImageFilter.GaussianBlur(120))
    img.paste(Image.new("RGB", (ш, в), (5, 5, 8)), (0, 0), тень)

    ФОТО_ПАПКА.mkdir(parents=True, exist_ok=True)
    имя = f"p{индекс:02d}-{вариант}.jpg"
    img.save(ФОТО_ПАПКА / имя, "JPEG", quality=86)
    return f"/demo-photos/{имя}"


def _возраст_в_дату(возраст: int) -> datetime:
    """День рождения под требуемый возраст, со сдвигом внутри года."""
    сегодня = datetime.now(timezone.utc)
    return сегодня.replace(year=сегодня.year - возраст) - timedelta(days=random.randint(10, 300))


async def развернуть(me_key: str, только_снос: bool) -> None:
    from sqlalchemy import delete, select
    from database.connection import async_session_factory
    from models.models import (
        ChatStreak, Like, Match, Message, Profile, StickerOwned, Story, User, UserHabit,
    )

    now = datetime.now(timezone.utc)

    async with async_session_factory() as s:
        # ── Снос прежнего демо ────────────────────────────────────
        старые = (
            await s.execute(select(User.id).where(User.phone.like("demo:%")))
        ).scalars().all()
        if старые:
            # Историй и стриков каскад БД касается через FK, но чистим явно
            # то, что ссылается на аудит-аккаунт не через demo-пользователей.
            await s.execute(delete(User).where(User.id.in_(старые)))
            log.info("снесено прежних демо-аккаунтов: %d", len(старые))
        if только_снос:
            await s.commit()
            return

        # ── Аудит-аккаунт (кого обвешиваем жизнью) ───────────────
        меня = (
            await s.execute(select(User).where(User.phone == me_key))
        ).scalar_one_or_none()
        if меня is None:
            меня = User(id=str(uuid.uuid4()), phone=me_key, role="user", is_verified=True)
            s.add(меня)
            await s.flush()
            log.info("создан аудит-аккаунт %s (%s)", me_key, меня.id)

        мой_профиль = await s.get(Profile, меня.id)
        if мой_профиль is None:
            мой_профиль = Profile(user_id=меня.id)
            s.add(мой_профиль)
        мой_профиль.display_name = мой_профиль.display_name or "Джакс"
        мой_профиль.gender = "male"
        мой_профиль.birth_date = _возраст_в_дату(28)
        мой_профиль.city = "Москва"
        мой_профиль.latitude, мой_профиль.longitude = КООРДИНАТЫ["Москва"]
        мой_профиль.bio = "Собираю инструменты и людей. Демо-аккаунт для аудита."
        мой_профиль.photos = [_портрет(99, 1), _портрет(99, 2)]
        мой_профиль.interests = ["код", "кофе", "горы"]
        мой_профиль.goal = "relationship"
        мой_профиль.looking_for = "any"
        мой_профиль.height_cm = 182

        # ── Демо-люди ─────────────────────────────────────────────
        люди: list[User] = []
        for i, (имя, пол, возраст, город, био, интересы, цель, связь, суб, mbti, рост) in enumerate(ЛЮДИ):
            u = User(
                id=str(uuid.uuid4()),
                phone=f"demo:{i:02d}",
                role="user",
                is_verified=(i % 3 == 0),
                last_seen_at=now - timedelta(minutes=random.randint(2, 900)),
            )
            s.add(u)
            await s.flush()
            фото = [_портрет(i, v) for v in (1, 2, 3)]
            ш, д = КООРДИНАТЫ[город]
            s.add(Profile(
                user_id=u.id,
                display_name=имя,
                gender=пол,
                birth_date=_возраст_в_дату(возраст),
                city=город,
                latitude=ш + random.uniform(-0.05, 0.05),
                longitude=д + random.uniform(-0.05, 0.05),
                bio=био,
                photos=фото,
                interests=интересы,
                goal=цель,
                relation_type=связь,
                subculture=суб,
                mbti=mbti,
                height_cm=рост,
                looking_for="any",
            ))
            люди.append(u)
        log.info("создано демо-анкет: %d", len(люди))

        # ── Входящие лайки (экран «Кто меня лайкнул») ────────────
        s.add(Like(liker_id=люди[3].id, liked_id=меня.id, type="like"))
        s.add(Like(liker_id=люди[4].id, liked_id=меня.id, type="superlike",
                   message="У тебя в профиле горы — я как раз ищу компанию на Эльбрус!"))
        s.add(Like(liker_id=люди[5].id, liked_id=меня.id, type="like"))

        # ── Мэтчи с перепиской ────────────────────────────────────
        def пара(a: str, b: str) -> tuple[str, str]:
            return (a, b) if a < b else (b, a)

        диалоги = [
            # (собеседник, [(кто, текст, минут назад, прочитано)], стрик)
            (люди[0], [
                ("их", "Привет! Увидела у тебя винил в интересах — что крутишь сейчас?", 400, True),
                ("я", "Привет! Сейчас Хвостенко, внезапно. А у тебя какой первый диск был?", 380, True),
                ("их", "Ого, неожиданно и очень хорошо. Первый — «Меланхолия» Шарлотты, найденная на барахолке", 350, True),
                ("я", "Барахолки — отдельный вид терапии. Надо сравнить находки", 320, True),
                ("их", "Давай! В субботу на Левше как раз развал", 15, False),
            ], 5),
            (люди[1], [
                ("их", "Твоё фото с гор — это Домбай?", 2000, True),
                ("я", "Архыз! Но Домбай в списке на этот сезон", 1900, True),
                ("их", "Тогда есть повод посоревноваться, кто быстрее спустится 😄", 1700, True),
            ], 0),
            (люди[6], [
                ("я", "Слушай, а синтезаторы аналоговые или в коробке?", 5000, True),
                ("их", "Оба! Прогретый Juno и куча плагинов. Заходи послушать, как это спорит между собой", 4800, True),
            ], 0),
        ]

        for собеседник, сообщения, стрик in диалоги:
            u1, u2 = пара(меня.id, собеседник.id)
            м = Match(id=str(uuid.uuid4()), user1_id=u1, user2_id=u2,
                      match_score=random.randint(71, 94),
                      created_at=now - timedelta(days=random.randint(2, 9)))
            s.add(м)
            await s.flush()
            for кто, текст, минут, прочитано in сообщения:
                s.add(Message(
                    match_id=м.id,
                    sender_id=меня.id if кто == "я" else собеседник.id,
                    text=текст,
                    created_at=now - timedelta(minutes=минут),
                    read_at=(now - timedelta(minutes=минут - 3)) if прочитано else None,
                ))
            if стрик:
                s.add(ChatStreak(
                    match_id=м.id, streak_days=стрик,
                    last_counted_for=now.replace(hour=0, minute=0, second=0, microsecond=0),
                ))
        log.info("мэтчей с перепиской: %d", len(диалоги))

        # ── Истории ───────────────────────────────────────────────
        for автор, подпись, часов_назад in (
            (люди[0], "Нашла то самое кафе", 3),
            (люди[1], "Репетиция 🔥", 7),
            (люди[6], "Новый патч звучит так", 12),
        ):
            профиль_автора = await s.get(Profile, автор.id)
            s.add(Story(
                user_id=автор.id,
                media_url=профиль_автора.photos[0],
                caption=подпись,
                audience="matches",
                created_at=now - timedelta(hours=часов_назад),
                expires_at=now + timedelta(hours=24 - часов_назад),
            ))
        s.add(Story(
            user_id=меня.id,
            media_url=мой_профиль.photos[0],
            caption="Проверяю, как это выглядит",
            audience="matches",
            created_at=now - timedelta(hours=1),
            expires_at=now + timedelta(hours=23),
        ))
        log.info("историй: 4")

        # ── План дня и коллекция ─────────────────────────────────
        полночь = now.replace(hour=0, minute=0, second=0, microsecond=0)
        s.add(UserHabit(user_id=меня.id, name="Написать первым", target_per_day=1,
                        today_count=1, counted_for_date=полночь))
        s.add(UserHabit(user_id=меня.id, name="Стакан воды", target_per_day=3,
                        today_count=1, counted_for_date=полночь))
        for код in ("heart", "coffee", "camera", "compass", "clover"):
            s.add(StickerOwned(user_id=меня.id, code=код, count=random.randint(1, 3)))

        await s.commit()
        log.info("готово: демо развёрнуто вокруг %s", me_key)


def main() -> int:
    p = argparse.ArgumentParser(description="Демо-данные Souldawn для локальной разработки")
    p.add_argument("--me", default="dev:audit-jax",
                   help="ключ phone аккаунта, вокруг которого строится демо (default: dev:audit-jax)")
    p.add_argument("--wipe", action="store_true", help="только удалить демо-данные")
    p.add_argument("-v", "--verbose", action="store_true")
    а = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if а.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )

    try:
        asyncio.run(развернуть(а.me, а.wipe))
    except Exception as e:  # инструмент для людей: падение объясняем словами
        log.error("не развернулось: %s", e)
        log.error("проверьте, что Postgres запущен и DATABASE_URL в .env верный")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
