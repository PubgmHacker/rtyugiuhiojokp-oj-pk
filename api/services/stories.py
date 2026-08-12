"""Истории: публикация, лента, просмотры, уборка.

Правило видимости одно и живёт здесь: лента собирается только по активным
парам. Расширять её на «всех, кто мог тебя увидеть» нельзя — это отдало бы
фотографии людям, которых человек не выбирал, и мы бы узнали об этом из
жалоб, а не из кода.

Аудитория "everyone" расширяет не ленту, а карточку: история появляется у
того, кто сам открыл анкету. Разница в том, кто сделал первый шаг.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models.models import Match, Profile, Story, StoryView
from services.r2_storage import delete_photo_from_r2

#: Сколько живёт история.
СРОК = timedelta(hours=24)

#: Больше за сутки — уже не «сегодня», а лента, и она вытесняет из
#: просмотрщика всех остальных: пролистать десять чужих кадров никто не
#: станет, а значит пострадают и те, кто выложил один.
ЛИМИТ_ЗА_СУТКИ = 10

AUDIENCE_MATCHES = "matches"
AUDIENCE_EVERYONE = "everyone"
AUDIENCES = frozenset({AUDIENCE_MATCHES, AUDIENCE_EVERYONE})

#: Подпись длиннее не читается на фотографии — она превращается в
#: полотно поверх кадра, ради которого историю и открыли.
MAX_CAPTION = 200


class ИсторияОтклонена(ValueError):
    """Лимит, аудитория или подпись не прошли проверку."""


@dataclass(frozen=True)
class Автор:
    """Строка в ленте историй."""

    user_id: str
    display_name: str
    avatar: str | None
    count: int
    latest_at: datetime
    has_unseen: bool


def _сейчас() -> datetime:
    return datetime.now(timezone.utc)


def _живые():
    """Условие «история актуальна». Одно на все запросы: разъехавшись,
    оно дало бы истории, видимые в ленте и недоступные при открытии."""
    return and_(Story.expires_at > _сейчас(), Story.is_hidden == False)  # noqa: E712


async def создать(
    session: AsyncSession,
    user_id: str,
    *,
    media_url: str,
    object_key: str,
    caption: str,
    audience: str,
) -> Story:
    """Опубликовать историю."""
    if audience not in AUDIENCES:
        raise ИсторияОтклонена("Неизвестная аудитория")

    caption = (caption or "").strip()[:MAX_CAPTION]

    result = await session.execute(
        select(func.count(Story.id)).where(
            and_(
                Story.user_id == user_id,
                Story.created_at > _сейчас() - СРОК,
            )
        )
    )
    if (result.scalar() or 0) >= ЛИМИТ_ЗА_СУТКИ:
        raise ИсторияОтклонена(
            f"Не больше {ЛИМИТ_ЗА_СУТКИ} историй за сутки"
        )

    story = Story(
        user_id=user_id,
        media_url=media_url,
        object_key=object_key,
        caption=caption,
        audience=audience,
        expires_at=_сейчас() + СРОК,
    )
    session.add(story)
    await session.flush()
    return story


async def _партнёры(session: AsyncSession, user_id: str) -> list[str]:
    """Кто в активных парах с человеком."""
    result = await session.execute(
        select(Match.user1_id, Match.user2_id).where(
            and_(
                or_(Match.user1_id == user_id, Match.user2_id == user_id),
                Match.is_active == True,  # noqa: E712
            )
        )
    )
    return [
        (u2 if u1 == user_id else u1) for u1, u2 in result.all()
    ]


async def лента(session: AsyncSession, user_id: str) -> list[Автор]:
    """Авторы с живыми историями — партнёры по парам.

    Сортировка: непросмотренные вперёд, внутри — по свежести. Так лента
    сама расходуется: просмотренное уезжает вправо и не мешает.
    """
    partners = await _партнёры(session, user_id)
    if not partners:
        return []

    # Одним запросом: агрегат по автору плюс число просмотренных мной.
    # Иначе на каждого партнёра пришлось бы по два запроса, и лента из
    # тридцати пар стала бы шестьюдесятью походами в базу.
    seen = (
        select(StoryView.story_id)
        .where(StoryView.viewer_id == user_id)
        .subquery()
    )
    # Считаем сначала по историям, анкету подшиваем ПОСЛЕ группировки.
    # Иначе Profile.photos (тип json) попадает в GROUP BY, а у json в
    # Postgres нет оператора равенства — запрос не строится вообще:
    # «could not identify an equality operator for type json», 500 на
    # каждую ленту, где у пары есть живая история. Пустая лента ошибку не
    # показывала: до запроса дело не доходило из-за раннего выхода выше.
    агрегат = (
        select(
            Story.user_id.label("user_id"),
            func.count(Story.id).label("count"),
            func.max(Story.created_at).label("latest"),
            func.count(seen.c.story_id).label("seen_count"),
        )
        .outerjoin(seen, seen.c.story_id == Story.id)
        .where(and_(Story.user_id.in_(partners), _живые()))
        .group_by(Story.user_id)
        .subquery()
    )
    result = await session.execute(
        select(
            агрегат.c.user_id,
            агрегат.c.count,
            агрегат.c.latest,
            агрегат.c.seen_count,
            Profile.display_name,
            Profile.photos,
        ).join(Profile, Profile.user_id == агрегат.c.user_id)
    )

    авторы: list[Автор] = []
    for uid, count, latest, seen_count, name, photos in result.all():
        авторы.append(
            Автор(
                user_id=uid,
                display_name=name or "Без имени",
                avatar=(photos or [None])[0] if photos else None,
                count=count,
                latest_at=latest,
                has_unseen=seen_count < count,
            )
        )

    авторы.sort(key=lambda a: (not a.has_unseen, -a.latest_at.timestamp()))
    return авторы


async def свои(session: AsyncSession, user_id: str) -> list[Story]:
    """Свои живые истории — от старой к новой, порядок просмотрщика."""
    result = await session.execute(
        select(Story)
        .where(and_(Story.user_id == user_id, _живые()))
        .order_by(Story.created_at)
    )
    return list(result.scalars().all())


async def доступ_к_автору(
    session: AsyncSession, viewer_id: str, author_id: str
) -> bool:
    """Может ли человек открыть истории этого автора.

    Свои — всегда. Пара — всегда. Иначе только если автор открыл историю
    для всех, и тогда решение принял он, а не мы.
    """
    if viewer_id == author_id:
        return True

    result = await session.execute(
        select(Match.id).where(
            and_(
                or_(
                    and_(Match.user1_id == viewer_id, Match.user2_id == author_id),
                    and_(Match.user1_id == author_id, Match.user2_id == viewer_id),
                ),
                Match.is_active == True,  # noqa: E712
            )
        )
    )
    if result.scalar_one_or_none():
        return True

    result = await session.execute(
        select(func.count(Story.id)).where(
            and_(
                Story.user_id == author_id,
                Story.audience == AUDIENCE_EVERYONE,
                _живые(),
            )
        )
    )
    return (result.scalar() or 0) > 0


async def истории_автора(
    session: AsyncSession, viewer_id: str, author_id: str
) -> list[Story]:
    """Живые истории автора, видимые этому человеку."""
    условие = [Story.user_id == author_id, _живые()]
    if viewer_id != author_id:
        # Пара видит всё, посторонний — только открытое для всех.
        # Проверку пары уже сделал доступ_к_автору; здесь сужаем выборку
        # для случая, когда пары нет.
        result = await session.execute(
            select(Match.id).where(
                and_(
                    or_(
                        and_(Match.user1_id == viewer_id, Match.user2_id == author_id),
                        and_(Match.user1_id == author_id, Match.user2_id == viewer_id),
                    ),
                    Match.is_active == True,  # noqa: E712
                )
            )
        )
        if not result.scalar_one_or_none():
            условие.append(Story.audience == AUDIENCE_EVERYONE)

    result = await session.execute(
        select(Story).where(and_(*условие)).order_by(Story.created_at)
    )
    return list(result.scalars().all())


async def просмотренные(
    session: AsyncSession, viewer_id: str, story_ids: list[str]
) -> set[str]:
    """Какие из этих историй человек уже видел."""
    if not story_ids:
        return set()
    result = await session.execute(
        select(StoryView.story_id).where(
            and_(
                StoryView.viewer_id == viewer_id,
                StoryView.story_id.in_(story_ids),
            )
        )
    )
    return set(result.scalars().all())


async def отметить_просмотр(
    session: AsyncSession, story_id: str, viewer_id: str
) -> None:
    """Записать просмотр.

    Счётчик поднимаем только при реальной вставке: просмотрщик дёргает
    ручку на каждом кадре, включая возврат назад, и без этого условия
    один зритель накрутил бы сотню просмотров.

    Свой просмотр не считаем — автор смотрит свою историю чаще всех, и
    его заходы сделали бы счётчик бессмысленным.
    """
    story = await session.get(Story, story_id)
    if story is None or story.user_id == viewer_id:
        return

    result = await session.execute(
        pg_insert(StoryView)
        .values(story_id=story_id, viewer_id=viewer_id)
        .on_conflict_do_nothing(constraint="uq_story_view")
        .returning(StoryView.id)
    )
    if result.scalar_one_or_none() is not None:
        story.views_count += 1
    await session.flush()


async def зрители(
    session: AsyncSession, story_id: str, limit: int = 100
) -> list[tuple[str, str, str | None, datetime]]:
    """Кто смотрел — только для автора. Свежие первыми."""
    result = await session.execute(
        select(
            StoryView.viewer_id,
            Profile.display_name,
            Profile.photos,
            StoryView.created_at,
        )
        .join(Profile, Profile.user_id == StoryView.viewer_id)
        .where(StoryView.story_id == story_id)
        .order_by(StoryView.created_at.desc())
        .limit(limit)
    )
    return [
        (uid, name or "Без имени", (photos or [None])[0] if photos else None, at)
        for uid, name, photos, at in result.all()
    ]


async def удалить(session: AsyncSession, story: Story) -> None:
    """Убрать историю вместе с файлом.

    Файл гасим до строки: осиротевшая строка чинится вручную, а
    осиротевший файл в R2 не находится вообще.
    """
    if story.object_key:
        try:
            await delete_photo_from_r2(story.object_key)
        except Exception:
            # Хранилище недоступно — историю всё равно убираем: для
            # человека важно, что её больше не видно, а не наш порядок.
            pass
    await session.delete(story)
    await session.flush()


async def удалить_истёкшие(session: AsyncSession, limit: int = 300) -> int:
    """Уборка. Возвращает число снятых историй.

    Порциями: одна транзакция на всё накопившееся за простой блокировала
    бы таблицу на минуты. Вызывать из суточной задачи.
    """
    result = await session.execute(
        select(Story)
        .where(Story.expires_at <= _сейчас())
        .order_by(Story.expires_at)
        .limit(limit)
    )
    истёкшие = list(result.scalars().all())
    if not истёкшие:
        return 0

    for story in истёкшие:
        if story.object_key:
            try:
                await delete_photo_from_r2(story.object_key)
            except Exception:
                pass

    await session.execute(
        delete(Story).where(Story.id.in_([s.id for s in истёкшие]))
    )
    await session.commit()
    return len(истёкшие)
