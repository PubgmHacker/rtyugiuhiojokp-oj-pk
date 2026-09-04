"""Голосовые и видеокружки в личке.

Правила проверяем на чистых функциях (`нормализовать_медиа`, сигнатуры
файлов) и на HTTP-эндпоинтах загрузки с подменёнными R2 и модерацией:
хранилища в тестах нет, а важны именно отказы — чужой файл, чужая папка,
неверная длительность, не-аудио под аудио-заголовком.
"""

from __future__ import annotations

import io
import uuid

import pytest
from httpx import ASGITransport, AsyncClient


R2 = "https://cdn.example.test"


@pytest.fixture
def r2(monkeypatch):
    from config import get_settings

    monkeypatch.setattr(get_settings(), "R2_PUBLIC_URL", R2)
    return R2


# ── нормализация пакета медиа ────────────────────────────────────


def test_медиа_из_папки_отправителя_принимается(r2):
    from services.chat_delivery import нормализовать_медиа

    me = str(uuid.uuid4())
    got = нормализовать_медиа(me, {
        "url": f"{r2}/chat-media/{me}/voice-1.webm",
        "kind": "voice", "duration": 12, "waveform": "0123456789ab",
    })
    assert got == {
        "url": f"{r2}/chat-media/{me}/voice-1.webm",
        "kind": "voice", "duration": 12, "shape": None,
        # Не-цифры из волны вычищены
        "waveform": "0123456789",
        "poster": None,
    }


def test_постер_кружка_только_из_своей_папки(r2):
    from services.chat_delivery import ДоставкаОтклонена, нормализовать_медиа

    me, other = str(uuid.uuid4()), str(uuid.uuid4())
    url = f"{r2}/chat-media/{me}/note-1.webm"
    ok = нормализовать_медиа(me, {
        "url": url, "kind": "video_note", "duration": 5, "shape": "heart",
        "poster": f"{r2}/chat-media/{me}/note-1.jpg",
    })
    assert ok["poster"] == f"{r2}/chat-media/{me}/note-1.jpg"

    # Чужой постер — это чужая картинка в чате мимо модерации
    with pytest.raises(ДоставкаОтклонена):
        нормализовать_медиа(me, {
            "url": url, "kind": "video_note", "duration": 5,
            "poster": f"{r2}/chat-media/{other}/note-1.jpg",
        })
    # Мусор вместо постера и постер у голосового — просто нет постера
    assert нормализовать_медиа(me, {"url": url, "kind": "video_note", "poster": 42})["poster"] is None
    assert нормализовать_медиа(me, {"url": url, "kind": "voice", "poster": f"{r2}/chat-media/{me}/a.jpg"})["poster"] is None


def test_чужой_хост_и_чужая_папка_отклоняются(r2):
    from services.chat_delivery import ДоставкаОтклонена, нормализовать_медиа

    me, other = str(uuid.uuid4()), str(uuid.uuid4())
    for url in (
        "https://evil.example/voice.webm",
        f"{r2}/chat-media/{other}/voice-1.webm",   # запись другого человека
        f"{r2}/photos/{me}/a.jpg",                  # не медиа-папка
        "",
    ):
        with pytest.raises(ДоставкаОтклонена) as e:
            нормализовать_медиа(me, {"url": url, "kind": "voice", "duration": 3})
        assert e.value.code == "foreign_media", url


def test_неизвестный_вид_и_не_словарь_это_bad_media(r2):
    from services.chat_delivery import ДоставкаОтклонена, нормализовать_медиа

    me = str(uuid.uuid4())
    with pytest.raises(ДоставкаОтклонена) as e:
        нормализовать_медиа(me, {"url": f"{r2}/chat-media/{me}/x.webm", "kind": "gif"})
    assert e.value.code == "bad_media"
    with pytest.raises(ДоставкаОтклонена):
        нормализовать_медиа(me, "not-a-dict")
    # Пусто — не медиа, а не ошибка
    assert нормализовать_медиа(me, None) is None
    assert нормализовать_медиа(me, "") is None


def test_кружок_форма_и_длительность_чинятся_молча(r2):
    from services.chat_delivery import нормализовать_медиа
    from services.media_notes import MAX_MEDIA_SECONDS

    me = str(uuid.uuid4())
    url = f"{r2}/chat-media/{me}/note-1.mp4"
    ok = нормализовать_медиа(me, {"url": url, "kind": "video_note", "duration": 7, "shape": "star"})
    assert ok["shape"] == "star" and ok["waveform"] is None

    weird = нормализовать_медиа(me, {
        "url": url, "kind": "video_note", "duration": 9999, "shape": "banana",
        "waveform": "123",  # у кружка волны нет
    })
    assert weird["shape"] == "circle"
    assert weird["duration"] == MAX_MEDIA_SECONDS
    assert weird["waveform"] is None

    # У голосового формы нет, даже если прислали
    voice = нормализовать_медиа(me, {"url": url, "kind": "voice", "duration": "x", "shape": "star"})
    assert voice["shape"] is None and voice["duration"] == 0


def test_превью_и_подпись_уведомления():
    from models.models import Message
    from services.chat_delivery import notify_text_for, превью_сообщения

    assert notify_text_for("привет", None, None) == "привет"
    assert notify_text_for("", None, {"kind": "voice"}) == "Голосовое сообщение"
    assert notify_text_for("", None, {"kind": "video_note"}) == "Видеосообщение"
    assert notify_text_for("", "https://x/1.jpg", None) == "Фотография"

    assert превью_сообщения(None) is None
    assert превью_сообщения(Message(text="", media_kind="voice", media_url="u")) == "Голосовое сообщение"
    assert превью_сообщения(Message(text="", image_url="i")) == "Фотография"
    assert превью_сообщения(Message(text="ок")) == "ок"


def test_сигнатуры_аудио_и_чистый_тип():
    from services.media_notes import looks_like_audio, чистый_тип

    assert чистый_тип("audio/webm;codecs=opus") == "audio/webm"
    assert чистый_тип(None) == ""
    assert looks_like_audio(b"\x1a\x45\xdf\xa3" + b"\0" * 20)      # webm
    assert looks_like_audio(b"OggS" + b"\0" * 20)                   # ogg
    assert looks_like_audio(b"\0\0\0\x18ftypM4A " + b"\0" * 8)      # m4a
    assert looks_like_audio(b"ID3" + b"\0" * 20)                    # mp3 с тегом
    assert looks_like_audio(b"\xff\xfb" + b"\0" * 20)               # mp3 фрейм
    assert looks_like_audio(b"RIFF\0\0\0\0WAVE" + b"\0" * 8)        # wav
    assert not looks_like_audio(b"PK\x03\x04" + b"\0" * 20)         # архив
    assert not looks_like_audio(b"short")


def test_формы_кружка_фиксированы_и_круг_первый():
    from services.media_notes import VIDEO_NOTE_SHAPES

    assert VIDEO_NOTE_SHAPES[0] == "circle"
    assert {"heart", "star", "hexagon", "tree", "flower", "squircle"} <= set(VIDEO_NOTE_SHAPES)


# ── HTTP: загрузка ───────────────────────────────────────────────


@pytest.fixture
async def клиент(app, monkeypatch):
    from middleware.auth import get_current_user
    from models.models import User
    import routers.upload as upload_mod

    me = User(id=str(uuid.uuid4()), telegram_id=777, role="user")
    залито: list[tuple[str, bytes, str]] = []

    async def _upload(key, data, ct):
        залито.append((key, data, ct))
        return f"{R2}/{key}"

    monkeypatch.setattr(upload_mod, "uploads_available", lambda: True)
    monkeypatch.setattr(upload_mod, "upload_photo_to_r2", _upload)
    app.dependency_overrides[get_current_user] = lambda: me

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.me = me  # type: ignore[attr-defined]
        c.залито = залито  # type: ignore[attr-defined]
        yield c

    app.dependency_overrides.pop(get_current_user, None)


async def test_голосовое_ложится_в_папку_отправителя(клиент, r2):
    webm = b"\x1a\x45\xdf\xa3" + b"\0" * 64
    r = await клиент.post(
        "/api/upload/voice",
        files={"file": ("v.webm", io.BytesIO(webm), "audio/webm;codecs=opus")},
        data={"duration": "12"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["duration"] == 12
    assert body["key"].startswith(f"chat-media/{клиент.me.id}/voice-")
    assert body["key"].endswith(".webm")
    assert body["url"] == f"{r2}/{body['key']}"
    # Content-Type в R2 уходит без параметров кодека
    assert клиент.залито[-1][2] == "audio/webm"


async def test_голосовое_отказы(клиент):
    webm = b"\x1a\x45\xdf\xa3" + b"\0" * 64

    r = await клиент.post("/api/upload/voice",
        files={"file": ("v.webm", io.BytesIO(webm), "audio/webm")}, data={"duration": "0"})
    assert r.status_code == 400 and "1 до 60" in r.json()["detail"]

    r = await клиент.post("/api/upload/voice",
        files={"file": ("v.webm", io.BytesIO(webm), "audio/webm")}, data={"duration": "61"})
    assert r.status_code == 400

    r = await клиент.post("/api/upload/voice",
        files={"file": ("v.webm", io.BytesIO(webm), "audio/webm")}, data={"duration": "abc"})
    assert r.status_code == 400 and "не число" in r.json()["detail"]

    r = await клиент.post("/api/upload/voice",
        files={"file": ("v.zip", io.BytesIO(b"PK\x03\x04" + b"\0" * 64), "audio/webm")},
        data={"duration": "3"})
    assert r.status_code == 400 and "не похож на аудио" in r.json()["detail"]

    r = await клиент.post("/api/upload/voice",
        files={"file": ("v.txt", io.BytesIO(webm), "text/plain")}, data={"duration": "3"})
    assert r.status_code == 400 and "не поддерживается" in r.json()["detail"]

    r = await клиент.post("/api/upload/voice",
        files={"file": ("v.webm", io.BytesIO(b""), "audio/webm")}, data={"duration": "3"})
    assert r.status_code == 400

    assert клиент.залито == []


async def test_загрузка_медиа_без_хранилища_503(клиент, monkeypatch):
    import routers.upload as upload_mod

    monkeypatch.setattr(upload_mod, "uploads_available", lambda: False)
    webm = b"\x1a\x45\xdf\xa3" + b"\0" * 64
    r = await клиент.post("/api/upload/voice",
        files={"file": ("v.webm", io.BytesIO(webm), "audio/webm")}, data={"duration": "3"})
    assert r.status_code == 503
    r = await клиент.post("/api/upload/video-note",
        files=[("file", ("n.webm", io.BytesIO(webm), "video/webm")),
               ("covers", ("c1.jpg", io.BytesIO(b"x"), "image/jpeg"))],
        data={"duration": "3"})
    assert r.status_code == 503


async def test_кружок_модерируется_по_кадрам_и_ложится_в_папку(клиент, r2, monkeypatch):
    import routers.upload as upload_mod

    увидено: dict = {}

    async def _модерация(session, user, covers, тип, метка):
        увидено.update(тип=тип, кадров=len(covers), user=user.id)
        return [], None

    monkeypatch.setattr(upload_mod, "модерировать_кадры", _модерация)
    # get_session лезет в базу — здесь она не нужна
    from database.connection import get_session

    async def _no_session():
        yield None

    клиент._transport.app.dependency_overrides[get_session] = _no_session  # type: ignore[attr-defined]
    try:
        webm = b"\x1a\x45\xdf\xa3" + b"\0" * 64
        r = await клиент.post(
            "/api/upload/video-note",
            files=[
                ("file", ("n.webm", io.BytesIO(webm), "video/webm;codecs=vp8,opus")),
                ("covers", ("c1.jpg", io.BytesIO(b"1"), "image/jpeg")),
                ("covers", ("c2.jpg", io.BytesIO(b"2"), "image/jpeg")),
                ("covers", ("c3.jpg", io.BytesIO(b"3"), "image/jpeg")),
            ],
            data={"duration": "45"},
        )
    finally:
        клиент._transport.app.dependency_overrides.pop(get_session, None)  # type: ignore[attr-defined]

    assert r.status_code == 200, r.text
    assert увидено == {"тип": "video_note", "кадров": 3, "user": клиент.me.id}
    body = r.json()
    assert body["key"].startswith(f"chat-media/{клиент.me.id}/note-") and body["key"].endswith(".webm")
    assert body["duration"] == 45
    assert body["poster"] is None  # кадров модерация не вернула — постера нет
    assert клиент.залито[-1][2] == "video/webm"


async def test_постер_кружка_ложится_рядом_с_видео(клиент, r2, monkeypatch):
    import routers.upload as upload_mod

    async def _модерация(session, user, covers, тип, метка):
        return [(b"\xff\xd8\xff" + b"\0" * 16, "image/jpeg", "jpg")], None

    monkeypatch.setattr(upload_mod, "модерировать_кадры", _модерация)
    from database.connection import get_session

    async def _no_session():
        yield None

    клиент._transport.app.dependency_overrides[get_session] = _no_session  # type: ignore[attr-defined]
    try:
        webm = b"\x1a\x45\xdf\xa3" + b"\0" * 64
        r = await клиент.post(
            "/api/upload/video-note",
            files=[
                ("file", ("n.webm", io.BytesIO(webm), "video/webm")),
                ("covers", ("c1.jpg", io.BytesIO(b"1"), "image/jpeg")),
            ],
            data={"duration": "9"},
        )
    finally:
        клиент._transport.app.dependency_overrides.pop(get_session, None)  # type: ignore[attr-defined]

    assert r.status_code == 200, r.text
    body = r.json()
    stem = body["key"].rsplit(".", 1)[0]
    assert body["poster"] == f"{r2}/{stem}.jpg"
    # Сначала постер, потом видео — оба в папке отправителя
    assert [z[2] for z in клиент.залито[-2:]] == ["image/jpeg", "video/webm"]
    assert клиент.залито[-2][0] == f"{stem}.jpg"


async def test_кружок_не_видео_и_без_кадров(клиент, monkeypatch):
    from database.connection import get_session

    async def _no_session():
        yield None

    app = клиент._transport.app  # type: ignore[attr-defined]
    app.dependency_overrides[get_session] = _no_session
    try:
        r = await клиент.post(
            "/api/upload/video-note",
            files=[("file", ("n.webm", io.BytesIO(b"PK\x03\x04" + b"\0" * 64), "video/webm")),
                   ("covers", ("c1.jpg", io.BytesIO(b"1"), "image/jpeg"))],
            data={"duration": "5"},
        )
        assert r.status_code == 400 and "не похож на видео" in r.json()["detail"]

        # Настоящая модерация кадров требует минимум три
        webm = b"\x1a\x45\xdf\xa3" + b"\0" * 64
        r = await клиент.post(
            "/api/upload/video-note",
            files=[("file", ("n.webm", io.BytesIO(webm), "video/webm")),
                   ("covers", ("c1.jpg", io.BytesIO(b"1"), "image/jpeg"))],
            data={"duration": "5"},
        )
        assert r.status_code == 400 and "3 кадра" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_session, None)
    assert клиент.залито == []


# ── схема ────────────────────────────────────────────────────────


def test_миграция_медиа_идёт_за_текущей_головой():
    """Голова у цепочки ровно одна, и медиа-ревизия лежит внутри неё.

    Имя головы здесь НЕ зашито намеренно: оно меняется с каждой новой
    миграцией, и зашитое значение превращало бы этот сторож в пункт
    ручного обслуживания — его правили бы не думая. Ветвление ловится
    самим фактом второй головы, а «медиа доедет до прода» — тем, что
    ревизия media лежит на пути от головы к корню.
    """
    import re
    from pathlib import Path

    versions = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    revs, вниз = {}, {}
    for f in versions.glob("*.py"):
        t = f.read_text(encoding="utf-8")
        r = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([0-9a-f]+)['\"]", t, re.M)
        d = re.search(r"^down_revision[^=]*=\s*['\"]?([0-9a-f]+|None)", t, re.M)
        if r:
            revs[r.group(1)] = f.name
            вниз[r.group(1)] = d.group(1) if d and d.group(1) != "None" else None
    heads = [r for r in revs if r not in set(вниз.values())]
    assert len(heads) == 1, f"цепочка разветвилась: {heads}"

    цепочка, узел = [], heads[0]
    while узел:
        assert узел in revs, f"ревизия {узел} потеряна, а на неё ссылаются"
        цепочка.append(узел)
        узел = вниз[узел]
    assert len(цепочка) == len(revs), "не все ревизии на одной линии"
    assert "d7a1c4e92b58" in цепочка, "медиа-ревизия выпала из цепочки"


def test_у_сообщения_есть_поля_медиа():
    from models.models import Message

    cols = {c.name for c in Message.__table__.columns}
    assert {
        "media_url", "media_kind", "media_duration", "media_shape", "media_waveform", "media_poster_url",
    } <= cols
