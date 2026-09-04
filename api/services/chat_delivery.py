"""Доставка сообщения в личный чат: запись, realtime и уведомления.

Сообщение в личку рождается в трёх местах — из WebSocket (`routers/chat.py`),
из HTTP-отправки (`routers/matches.py`) и из пересыла ролика
(`routers/reels.py`). Пока путь был один, фан-аут жил прямо в обработчике
сокета; второй источник его не повторил, и пересланный ролик молча ложился в
базу: собеседник с открытым чатом ничего не видел, пуш не уходил, бот не
узнавал. Это тот же сорт расхождения, что аудит нашёл в `hide_age` —
правильный код есть, но ровно в одной копии.

Поэтому запись и фан-аут лежат здесь, а роутеры только вызывают. Порядок
важен: сначала коммит, потом рассылка. Событие о несохранённом сообщении хуже,
чем сохранённое сообщение без события, — второе исправит перезагрузка чата.

По той же причине здесь живут и ПРАВИЛА отправки — чужая картинка и «одно
письмо до ответа». Пока они стояли в роутерах, каждый новый путь заводил свою
копию или обходился без них: сокет проверял картинку, HTTP — нет; HTTP
проверял письмо, `POST /matches/direct` — нет. Здесь же они проверяются в ТОЙ
ЖЕ транзакции, что и вставка сообщения, поэтому между проверкой и записью не
может вклиниться параллельный запрос.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy import text as sa_text

from database.connection import async_session_factory
from models.models import Match, Message, MessageReaction, Profile, Reel
from services.analytics import EVENT_FIRST_MESSAGE, track
from services.direct_messages import (
    DirectDenied,
    can_send_message,
    mark_answered_if_needed,
)
from services.media_notes import MAX_MEDIA_SECONDS, VIDEO_NOTE_SHAPES
from services.public_profile import наша_картинка
from services.reactions import REACTION_KEYS, нормализовать_реакцию
from services.push import is_configured, notify_new_message
from services.realtime import get_redis, publish_bot_event
from services.streaks import touch_streak_for_message
from services.ws_manager import manager

logger = logging.getLogger(__name__)

#: Чем короткое уведомление подписывает пересланный ролик. В пуше и в Telegram
#: нельзя показать само видео, а «прислал сообщение» без подписи непонятно.
REEL_FALLBACK_TEXT = "прислал видео"

#: Картинка принимается только из нашего хранилища. Пакет собирает клиент, и в
#: обход интерфейса (загрузки фото в чат в нём нет) сюда можно было положить
#: ссылку на что угодно: она показывалась собеседнику как <img>, не увидев ни
#: AI-модерации, ни санитайзера.
DENIED_FOREIGN_IMAGE = DirectDenied(
    "foreign_image", "Картинку можно отправить только загрузкой"
)

#: Голосовое и кружок — те же правила, что у картинки, плюс одно: файл должен
#: лежать в папке ОТПРАВИТЕЛЯ (chat-media/{sender}/). Иначе чужую запись из
#: другого чата можно было бы переслать как свою — голосом другого человека.
DENIED_FOREIGN_MEDIA = DirectDenied(
    "foreign_media", "Голосовое или видео можно отправить только записью"
)
DENIED_BAD_MEDIA = DirectDenied("bad_media", "Медиа не распознано")

#: Чем подписывать медиа там, где его нельзя показать: список чатов,
#: Telegram-уведомление, пуш.
MEDIA_FALLBACK_TEXT = {
    "voice": "Голосовое сообщение",
    "video_note": "Видеосообщение",
}

#: Столбиков волны в голосовом — цифр 0–9 в строке. Больше не нужно: пузырь
#: шириной 200px не покажет и этого.
MAX_WAVEFORM_LEN = 64

#: Сколько букв цитаты уезжает клиенту. Полоска над ответом — одна строка,
#: длиннее её всё равно не видно, а таскать двухкилобайтный текст в каждом
#: ответе на него — платить трафиком за невидимое.
REPLY_PREVIEW_LEN = 140

#: Реакций в минуту от одного человека. Отдельно от сообщений (20/мин):
#: реакция — это UPDATE одной строки без AI-модерации и без пуша, и она
#: законно идёт очередями, когда человек разбирает накопившуюся переписку.
#: Общий с сообщениями счётчик наказывал бы за это молчанием чата.
REACTION_FLOOD_PER_MINUTE = 60

DENIED_REACTION_FLOOD = DirectDenied(
    "reaction_flood", "Слишком много реакций подряд — подождите минуту"
)


class ДоставкаОтклонена(Exception):
    """Сообщение не сохранено: правило чата не пропустило.

    Исключение, а не `None`, потому что `None` у `save_message` уже занят
    другим смыслом («мэтча больше нет»), а звать эти случаи одинаково значило
    бы показать человеку «чат не найден» вместо настоящей причины.
    """

    def __init__(self, отказ: DirectDenied) -> None:
        super().__init__(отказ.detail)
        self.отказ = отказ

    @property
    def code(self) -> str:
        return self.отказ.code

    @property
    def detail(self) -> str:
        return self.отказ.detail


#: Антифлуд лички: сообщений в минуту от одного человека суммарно по всем его
#: чатам. Комнаты считают SQL-запросом (routers/rooms.py::check_flood), но для
#: лички так нельзя: Message — самая большая таблица, индекса по sender_id у
#: неё нет, и каждый флуд-чек превращался бы в скан. Поэтому Redis.
#:
#: 20 — вдвое щедрее комнатных десяти: там лимит на одну комнату, здесь — на
#: все чаты разом, а живая переписка репликами по слову легко даёт сообщение
#: раз в три-четыре секунды. Боту-спамеру всё равно не хватит.
CHAT_FLOOD_PER_MINUTE = 20

DENIED_FLOOD = DirectDenied(
    "flood", "Слишком много сообщений подряд — подождите минуту"
)


async def check_chat_flood(sender_id: str) -> None:
    """Антифлуд лички. Зовётся в роутерах ДО модерации текста, не здесь.

    Не внутри `save_message`: до него сообщение уже прошло `moderate_text`, а
    главный расход при флуде — именно платные AI-вызовы, их и надо отсечь
    первыми. Поэтому каждая точка отправки (WebSocket, HTTP-отправка, пересыл
    ролика) обязана позвать проверку сама; что ни одна не забыла — сторожит
    tests/test_chat_flood.py: незакрытая точка обнуляет лимит целиком.

    Окно фиксированное, как в middleware/rate_limit: ключ включает номер
    минуты и истекает сам. При сбое Redis пропускаем: личка — не перебор
    кодов, минута без антифлуда лучше чата, лежащего вместе с кешем.
    """
    await _минутное_окно(
        f"dating:chatflood:{sender_id}", CHAT_FLOOD_PER_MINUTE, DENIED_FLOOD
    )


async def check_reaction_flood(user_id: str) -> None:
    """Антифлуд реакций — своё окно, вдвое шире сообщений (см. константу)."""
    await _минутное_окно(
        f"dating:reactflood:{user_id}",
        REACTION_FLOOD_PER_MINUTE,
        DENIED_REACTION_FLOOD,
    )


async def _минутное_окно(префикс: str, лимит: int, отказ: DirectDenied) -> None:
    """Счётчик в Redis на текущую минуту. Сбой кеша — пропускаем."""
    try:
        r = await get_redis()
        bucket = int(time.time()) // 60
        key = f"{префикс}:{bucket}"
        used = await r.incr(key)
        if used == 1:
            await r.expire(key, 60)
    except Exception as e:
        logger.error(f"Flood check failed ({префикс}): {e}")
        return
    if used > лимит:
        raise ДоставкаОтклонена(отказ)


def наше_медиа(url: str | None, sender_id: str) -> bool:
    """Лежит ли файл в нашем R2 в папке именно этого отправителя."""
    if not url:
        return False
    from config import get_settings

    prefix = (get_settings().R2_PUBLIC_URL or "").rstrip("/") + "/"
    if prefix == "/":
        return False
    return url.startswith(f"{prefix}chat-media/{sender_id}/")


def нормализовать_медиа(sender_id: str, raw: object) -> dict | None:
    """Пакет медиа из клиента → проверенный словарь для записи, или None.

    Отказ — `ДоставкаОтклонена`, как у чужой картинки: чужой файл (или файл
    из чужой папки) — не «странный ввод», а попытка обойти запись.
    Длительность и форма чинятся молча: минута сверх лимита режется, а
    неизвестная форма становится кругом — за это человека не наказывают.
    """
    if raw is None or raw == "":
        return None
    if not isinstance(raw, dict):
        raise ДоставкаОтклонена(DENIED_BAD_MEDIA)

    kind = raw.get("kind")
    if kind not in MEDIA_FALLBACK_TEXT:
        raise ДоставкаОтклонена(DENIED_BAD_MEDIA)

    url = raw.get("url")
    if not isinstance(url, str) or not наше_медиа(url, sender_id):
        raise ДоставкаОтклонена(DENIED_FOREIGN_MEDIA)

    try:
        duration = int(raw.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    duration = max(0, min(duration, MAX_MEDIA_SECONDS))

    shape = raw.get("shape") if kind == "video_note" else None
    if shape not in VIDEO_NOTE_SHAPES:
        shape = VIDEO_NOTE_SHAPES[0] if kind == "video_note" else None

    waveform = None
    if kind == "voice":
        сырое = raw.get("waveform")
        if isinstance(сырое, str):
            цифры = "".join(ch for ch in сырое if ch.isdigit())[:MAX_WAVEFORM_LEN]
            waveform = цифры or None

    # Постер кружка — тоже файл, и правило то же: только из папки отправителя.
    # Чужая ссылка здесь — способ подсунуть картинку мимо модерации.
    poster = raw.get("poster") if kind == "video_note" else None
    if not isinstance(poster, str) or not poster:
        poster = None
    elif not наше_медиа(poster, sender_id):
        raise ДоставкаОтклонена(DENIED_FOREIGN_MEDIA)

    return {
        "url": url,
        "kind": kind,
        "duration": duration,
        "shape": shape,
        "waveform": waveform,
        "poster": poster,
    }


def media_preview(m: Message) -> dict | None:
    """Медиа сообщения — единая форма для REST и для WebSocket."""
    if not m.media_url or not m.media_kind:
        return None
    return {
        "url": m.media_url,
        "kind": m.media_kind,
        "duration": m.media_duration or 0,
        "shape": m.media_shape,
        "waveform": m.media_waveform,
        "poster": m.media_poster_url,
    }


def вид_сообщения(m: Message) -> str:
    """Чем сообщение было: text | photo | reel | voice | video_note."""
    if m.media_kind:
        return m.media_kind
    if m.reel_id:
        return "reel"
    if m.image_url:
        return "photo"
    return "text"


def превью_ответа(m: Message | None) -> dict | None:
    """Цитата над ответом — единая форма для REST и для WebSocket.

    Имя автора не кладём: в личке собеседников двое, и клиент знает обоих по
    `sender_id`. Лишний JOIN к профилям на каждое сообщение страницы стоил бы
    дороже, чем экономит.

    Кадр и форма кружка — ради ответа кружком на кружок: без них цитата на
    видеосообщение выглядит как ответ на пустоту, потому что текста там нет.
    """
    if m is None:
        return None
    вид = вид_сообщения(m)
    return {
        "id": m.id,
        "sender_id": m.sender_id,
        "text": (m.text or "")[:REPLY_PREVIEW_LEN],
        "kind": вид,
        "shape": m.media_shape if вид == "video_note" else None,
        "poster": m.media_poster_url if вид == "video_note" else None,
        "image_url": m.image_url if вид == "photo" else None,
        "duration": (m.media_duration or 0) if m.media_kind else 0,
    }


def свод_реакций(строки) -> list[dict]:
    """Реакции сообщения → [{key, users}] в порядке REACTION_KEYS.

    Отдаём не «моя/чужая», а список авторов: одно и то же событие уходит
    обоим собеседникам, и «моя» у них разная. Считать её на сервере значило
    бы слать два разных кадра в один чат — самый простой способ развести
    состояние клиентов. Клиент смотрит, есть ли он в списке.
    """
    по_ключу: dict[str, list[str]] = {}
    for r in строки:
        по_ключу.setdefault(r.key, []).append(r.user_id)
    return [
        {"key": k, "users": по_ключу[k]} for k in REACTION_KEYS if k in по_ключу
    ]


async def реакции_страницы(session, message_ids: list[str]) -> dict[str, list[dict]]:
    """Реакции для пачки сообщений одним запросом, а не по запросу на каждое."""
    if not message_ids:
        return {}
    result = await session.execute(
        select(MessageReaction).where(MessageReaction.message_id.in_(message_ids))
    )
    по_сообщению: dict[str, list] = {}
    for r in result.scalars().all():
        по_сообщению.setdefault(r.message_id, []).append(r)
    return {mid: свод_реакций(строки) for mid, строки in по_сообщению.items()}


async def set_reaction(
    match_id: str, message_id: str, user_id: str, raw_key: object
) -> Optional[dict]:
    """Поставить, сменить или снять реакцию. None — сообщения нет в этом чате.

    Повторное нажатие того же кода снимает реакцию: это ожидание из всех
    мессенджеров, и без него единственный способ передумать — искать
    крестик. Другой код заменяет строку, потому что реакция одна на человека.

    Проверка «сообщение из ЭТОГО мэтча» обязательна: id сообщения угадать
    нельзя, но подставить чужой из другой своей переписки — можно, и тогда
    реакция ушла бы в чат, где её никто не ждёт.
    """
    ключ = нормализовать_реакцию(raw_key)

    async with async_session_factory() as session:
        async with session.begin():
            result = await session.execute(
                select(Message).where(and_(
                    Message.id == message_id, Message.match_id == match_id
                ))
            )
            if result.scalar_one_or_none() is None:
                return None

            result = await session.execute(
                select(MessageReaction).where(and_(
                    MessageReaction.message_id == message_id,
                    MessageReaction.user_id == user_id,
                ))
            )
            своя = result.scalar_one_or_none()

            if ключ is None or (своя is not None and своя.key == ключ):
                if своя is not None:
                    await session.delete(своя)
            elif своя is not None:
                своя.key = ключ
            else:
                session.add(MessageReaction(
                    message_id=message_id, user_id=user_id, key=ключ
                ))
            await session.flush()

            result = await session.execute(
                select(MessageReaction).where(
                    MessageReaction.message_id == message_id
                )
            )
            return {
                "type": "reaction",
                "match_id": match_id,
                "message_id": message_id,
                "reactions": свод_реакций(result.scalars().all()),
            }


def notify_text_for(text: str, image_url: str | None, media: dict | None) -> str:
    """Чем подписать сообщение там, где его нельзя показать целиком."""
    if text:
        return text
    if media:
        return MEDIA_FALLBACK_TEXT.get(media.get("kind") or "", "Сообщение")
    if image_url:
        return "Фотография"
    return ""


def превью_сообщения(m: Message | None) -> str | None:
    """Строка для списка чатов: текст, иначе подпись медиа/фото/ролика."""
    if m is None:
        return None
    if m.text:
        return m.text
    if m.media_kind:
        return MEDIA_FALLBACK_TEXT.get(m.media_kind, "Сообщение")
    if m.image_url:
        return "Фотография"
    # Пересланный ролик без подписи оставлял строку пустой, и в списке
    # чатов беседа выглядела так, будто в ней ничего не происходило.
    return "Видео" if m.reel_id else None


def вид_превью(m: Message | None) -> str | None:
    """Чем было последнее сообщение — код для значка в списке чатов.

    Списку нужен код, а не подпись: значок микрофона, кружка или камеры он
    рисует сам, а разбирать обратно строку «Голосовое сообщение» пришлось бы
    сравнением с переводом. Строка остаётся для тех мест, где значка нет
    (уведомления, пуши).
    """
    if m is None:
        return None
    if m.media_kind:
        return m.media_kind
    if m.image_url:
        return "photo"
    if m.reel_id:
        return "reel"
    return "text" if m.text else None


def reel_preview(reel: Reel | None) -> dict | None:
    """Превью ролика для сообщения — единая форма для REST и для WebSocket.

    Скрытый модерацией ролик не отдаём даже в старой переписке: снятое с показа
    видео не должно продолжать ходить по чатам.
    """
    if not reel or reel.is_hidden:
        return None
    return {
        "id": reel.id,
        "video_url": reel.video_url,
        "cover_url": reel.cover_url,
        "caption": reel.caption,
    }


async def save_message(
    match_id: str,
    sender_id: str,
    text: str,
    image_url: Optional[str] = None,
    reel_id: Optional[str] = None,
    media: Optional[dict] = None,
    reply_to_id: Optional[str] = None,
) -> Optional[dict]:
    """Сохранить сообщение и собрать payload события. None — мэтч уже неактивен.

    Мэтч перепроверяется здесь, а не только у вызывающего: сокет живёт долго и
    пару могли развести, пока он был открыт.

    Здесь же проходят правила отправки, и оба — внутри той же транзакции, что и
    вставка. Раньше «одно письмо до ответа» проверялось в роутере отдельной
    сессией: между проверкой и записью успевал пройти второй запрос, и оба
    письма ложились в базу. Advisory-lock на чат закрывает эту щель тем же
    приёмом, что лайки и кейсы.

    Отказ — исключение `ДоставкаОтклонена`, а не `None`: `None` уже значит
    «мэтча нет», и смешивать их значило бы отвечать человеку «чат не найден»
    там, где он просто исчерпал лимит.
    """
    if not наша_картинка(image_url):
        raise ДоставкаОтклонена(DENIED_FOREIGN_IMAGE)
    # Медиа перепроверяем и здесь, а не только в роутере: путей в save_message
    # несколько, и словарь мог собрать кто угодно
    media = нормализовать_медиа(sender_id, media)

    async with async_session_factory() as session:
        async with session.begin():
            # Лок на беседу, а не на отправителя: гонка тут между двумя
            # письмами в ОДИН чат, и взят до чтения мэтча — иначе второй
            # запрос успеет прочитать «сообщений ноль» до записи первого
            await session.execute(
                sa_text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": f"dating:chat:{match_id}"},
            )

            result = await session.execute(
                select(Match).where(and_(Match.id == match_id, Match.is_active == True))  # noqa: E712
            )
            match = result.scalar_one_or_none()
            if not match:
                return None

            denied = await can_send_message(session, match, sender_id)
            if denied:
                raise ДоставкаОтклонена(denied)

            # Цитата: сообщение обязано быть из ЭТОЙ переписки. Чужой id не
            # ошибка запроса, а попытка процитировать чужой чат, и молчаливое
            # обнуление тут правильнее отказа: ответ на реплику, которую уже
            # удалили, всё равно должен уйти — просто без цитаты.
            цель = None
            if reply_to_id:
                result = await session.execute(
                    select(Message).where(and_(
                        Message.id == reply_to_id, Message.match_id == match_id
                    ))
                )
                цель = result.scalar_one_or_none()

            # Флаг «ответили» ставится тут же: он снимает лимит с отправителя,
            # и разъехаться с фактом сообщения не должен ни на одном пути
            await mark_answered_if_needed(match, sender_id)

            # Стрик: +1 день, если это первое сообщение сегодня. Читаем эту
            # ветку до флага answer-статуса: иначе при повторном открытии
            # окна неизвестно, какой из флагов должен победить.
            await touch_streak_for_message(session, match.id)

            message = Message(
                match_id=match_id,
                sender_id=sender_id,
                text=text,
                image_url=image_url,
                reel_id=reel_id,
                media_url=media["url"] if media else None,
                media_kind=media["kind"] if media else None,
                media_duration=media["duration"] if media else None,
                media_shape=media["shape"] if media else None,
                media_waveform=media["waveform"] if media else None,
                media_poster_url=media.get("poster") if media else None,
                reply_to_id=цель.id if цель is not None else None,
            )
            session.add(message)
            await session.flush()

            # Веха воронки: первое отправленное сообщение — общий путь
            # доставки, сюда сходятся и чат, и direct-письма. В транзакции
            # вставки: откат не оставит события. Повторы гасит dedup_key
            await track(session, sender_id, EVENT_FIRST_MESSAGE, once=True)

            preview = None
            if reel_id:
                result = await session.execute(select(Reel).where(Reel.id == reel_id))
                preview = reel_preview(result.scalar_one_or_none())

            return {
                "type": "message",
                "id": message.id,
                "match_id": match_id,
                "sender_id": sender_id,
                "text": text,
                "image_url": image_url,
                # Форма та же, что у GET /matches/{id}/messages: иначе клиенту
                # пришлось бы рисовать пересланный ролик двумя разными ветками
                "reel": preview,
                "media": media_preview(message),
                "reply_to": превью_ответа(цель),
                # Свежее сообщение реакций не имеет — но поле должно быть
                # всегда: клиент не должен различать «нет реакций» и «поле
                # из другой ветки кода»
                "reactions": [],
                "created_at": message.created_at.isoformat() if message.created_at else None,
            }


async def _push_notification(
    match_id: str, sender_id: str, receiver_id: str, text: str,
) -> None:
    """Пуш в iOS — своя сессия, сокет её не держит.

    Сессия закрывается до отправки: держать её открытой всё время, пока
    отвечает APNs (до 10 с на устройство), значило бы занимать соединение из
    пула на разговор с чужим сервером.
    """
    if not is_configured():
        return
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(Profile.display_name).where(Profile.user_id == sender_id)
            )
            sender_name = result.scalar_one_or_none() or ""
    except Exception as e:
        logger.error(f"Message push name failed ({match_id}): {e}")
        return

    await notify_new_message(receiver_id, sender_name, text, match_id)


async def fan_out(
    payload: dict,
    match_id: str,
    sender_id: str,
    receiver_id: str,
    notify_text: str,
) -> None:
    """Разослать сохранённое сообщение: WebSocket, Telegram, пуш.

    `publish`, а не `broadcast`: собеседник может сидеть на другом инстансе API,
    туда событие дойдёт только через Redis.

    Telegram и пуш — только если получателя нет в чате ни на одном инстансе:
    иначе человек с открытым приложением получает то же сообщение трижды.
    """
    await manager.publish(match_id, payload)

    if await manager.is_user_online(match_id, receiver_id):
        return

    await publish_bot_event({
        "type": "new_message",
        "match_id": match_id,
        "sender_id": sender_id,
        "receiver_id": receiver_id,
        "text": notify_text[:200],
    })
    await _push_notification(match_id, sender_id, receiver_id, notify_text)
