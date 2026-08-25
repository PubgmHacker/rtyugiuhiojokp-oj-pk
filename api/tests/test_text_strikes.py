"""Текстовые страйки с категориями (А1): счёт, пороги, бан на пороге.

Что закрепляется:

* нормализация вердиктов: текстовый blocked без валидной категории падает в
  "text" (самое мягкое правило), фото-blocked без категории остаётся БЕЗ
  категории — отказ без страйка, фото-модель ошибается чаще текстовой;
* text_strike_count считает только blocked своей категории в своём окне и
  обрезается разбаном (AMNESTY_TYPES);
* register_text_strike: до порога — предупреждение со счётом, на пороге — бан
  (контракт: текущее нарушение уже в журнале), админов автоматика не банит;
* enforce_text_verdict: 422 со счётом до порога, готовый 403 после бана;
* фото-роутеры (upload/stories/reels) вешают страйк только за category "ad";
* контентные страйки (А2): снятая по жалобам единица контента пишет автору
  content_removed, третья за 90 дней банит лестницей content; забаненному
  новые страйки не копятся — жалобы на старый контент не двигают лестницу;
* паритет бот↔API: бот-канал живёт в другом venv, его константы объявлены
  сырыми литералами и сверяются с апишными через ast — расхождение правил
  между каналами означало бы разное наказание за один и тот же текст.

Журнал — настоящая таблица на SQLite, как в test_unban_purchase: окно и
категория — это SQL, фейковая сессия проверяла бы plumbing, а не срез.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tests.test_unban_purchase import _в_боте, _журнал_на_sqlite

_КОРЕНЬ = Path(__file__).resolve().parents[2]


# ── Заготовки ─────────────────────────────────────────────────────

class _Сессия:
    async def flush(self):
        pass


@pytest.fixture
def тихий_бан(monkeypatch):
    """Заглушить побочные эффекты бана, оставив журнал настоящим."""
    import services.enforcement as e
    import services.realtime as rt

    class _Redis:
        async def publish(self, *_a, **_kw):
            pass

    async def _редис():
        return _Redis()

    async def _тихо(*a, **kw):
        return True

    monkeypatch.setattr(rt, "get_redis", _редис)
    monkeypatch.setattr(e, "remember_ban", _тихо)
    monkeypatch.setattr(e, "revoke_all_for_user", _тихо)


def _нарушитель(**kw):
    основа = dict(
        id="u1", role="user", telegram_id=1, apple_id=None,
        is_banned=False, banned_until=None,
    )
    основа.update(kw)
    return SimpleNamespace(**основа)


async def _страйк(
    фабрика, модель, user_id, category,
    дней_назад=0.0, result="blocked", content_type="bio",
):
    """Запись журнала с категорией — как её пишет log_moderation."""
    момент = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=дней_назад)
    async with фабрика() as session:
        session.add(
            модель(
                user_id=user_id, content_type=content_type, content="",
                result=result, action="none", category=category,
                reason="", created_at=момент,
            )
        )
        await session.commit()


# ── Нормализация вердиктов ────────────────────────────────────────

@pytest.mark.parametrize(
    "сырой, категория",
    [
        ({"blocked": True, "category": "ad"}, "ad"),
        ({"blocked": True, "category": "heavy"}, "heavy"),
        ({"blocked": True}, "text"),
        ({"blocked": True, "category": "выдумка"}, "text"),
        ({"blocked": True, "category": ""}, "text"),
        ({"blocked": False, "category": "ad"}, ""),
    ],
)
def test_нормализация_текста(сырой, категория):
    from services.ai_moderation import _normalize_text_verdict

    итог = _normalize_text_verdict(сырой)
    assert итог["category"] == категория
    assert итог["blocked"] is bool(сырой.get("blocked"))
    assert итог["safe"] is (not сырой.get("blocked"))


@pytest.mark.parametrize(
    "сырой, категория",
    [
        ({"blocked": True, "category": "ad"}, "ad"),
        # Блок без категории (нудити и прочее) НЕ падает в "text": отказ
        # без страйка — иначе каждая ошибка фото-модели вела бы к бану
        ({"blocked": True, "reason": "nudity"}, ""),
        ({"blocked": True, "category": "text"}, ""),
        ({"blocked": False, "category": "ad"}, ""),
    ],
)
def test_нормализация_фото(сырой, категория):
    from services.ai_moderation import _normalize_image_verdict

    итог = _normalize_image_verdict(сырой)
    assert итог["category"] == категория
    assert итог["blocked"] is bool(сырой.get("blocked"))


# ── text_strike_count: срез журнала ───────────────────────────────

async def test_счёт_только_своя_категория_и_окно(monkeypatch):
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _страйк(фабрика, Журнал, "u1", "ad", дней_назад=1)
    await _страйк(фабрика, Журнал, "u1", "ad", дней_назад=29)
    await _страйк(фабрика, Журнал, "u1", "ad", дней_назад=31)          # за окном
    await _страйк(фабрика, Журнал, "u1", "text", дней_назад=1)         # чужая категория
    await _страйк(фабрика, Журнал, "u1", "ad", дней_назад=2, result="safe")  # не blocked
    await _страйк(фабрика, Журнал, "другой", "ad", дней_назад=1)       # чужой юзер

    assert await e.text_strike_count("u1", "ad", timedelta(days=30)) == 2


async def test_счёт_обрезается_разбаном(monkeypatch):
    """Платный или админский разбан обнуляет счёт: в бан ведут только новые."""
    from tests.test_unban_purchase import _записать

    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _страйк(фабрика, Журнал, "u1", "ad", дней_назад=5)
    await _страйк(фабрика, Журнал, "u1", "ad", дней_назад=4)
    await _записать(фабрика, Журнал, "u1", "unban_purchase", "safe", дней_назад=3)
    await _страйк(фабрика, Журнал, "u1", "ad", дней_назад=1)

    assert await e.text_strike_count("u1", "ad", timedelta(days=30)) == 1


async def test_сбой_журнала_не_даёт_страйков(monkeypatch):
    import services.enforcement as e

    class _Ломаный:
        def __call__(self):
            raise RuntimeError("db down")

    monkeypatch.setattr("database.connection.async_session_factory", _Ломаный())
    assert await e.text_strike_count("u1", "ad", timedelta(days=30)) == 0


# ── register_text_strike: предупреждение и бан ────────────────────

async def test_сейф_и_категория_без_правила_не_считаются(monkeypatch):
    import services.enforcement as e

    await _журнал_на_sqlite(monkeypatch)
    user = _нарушитель()
    assert await e.register_text_strike(_Сессия(), user, {"blocked": False}) is None
    assert await e.register_text_strike(
        _Сессия(), user, {"blocked": True, "category": "identity"}
    ) is None


async def test_до_порога_предупреждение_со_счётом(monkeypatch):
    """Контракт: текущее нарушение уже в журнале — счёт включает его."""
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _страйк(фабрика, Журнал, "u1", "ad")  # текущее, записал log_moderation

    user = _нарушитель()
    исход = await e.register_text_strike(
        _Сессия(), user, {"blocked": True, "category": "ad"}
    )
    assert (исход.count, исход.limit, исход.banned) == (1, 3, False)
    assert user.is_banned is False
    assert "Нарушение 1 из 3" in исход.warning_text()


@pytest.mark.parametrize("категория, порог", [("ad", 3), ("heavy", 2), ("text", 5)])
async def test_порог_категории_банит(monkeypatch, тихий_бан, категория, порог):
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    for _ in range(порог):
        await _страйк(фабрика, Журнал, "u1", категория)

    user = _нарушитель()
    исход = await e.register_text_strike(
        _Сессия(), user, {"blocked": True, "category": категория}
    )
    assert исход.banned is True
    assert user.is_banned is True
    # Первая ступень лестницы категории, а не вечный бан
    assert user.banned_until is not None
    assert исход.banned_until == user.banned_until


async def test_блок_без_категории_идёт_в_text(monkeypatch):
    """Старый формат вердикта (без category) наказывается по самому мягкому."""
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _страйк(фабрика, Журнал, "u1", "text")

    исход = await e.register_text_strike(_Сессия(), _нарушитель(), {"blocked": True})
    assert (исход.category, исход.limit) == ("text", 5)


async def test_админа_порог_не_банит(monkeypatch, тихий_бан):
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    for _ in range(3):
        await _страйк(фабрика, Журнал, "a1", "ad")

    админ = _нарушитель(id="a1", role="admin")
    исход = await e.register_text_strike(
        _Сессия(), админ, {"blocked": True, "category": "ad"}
    )
    assert исход.banned is False
    assert админ.is_banned is False


# ── enforce_text_verdict: единый REST-исход ───────────────────────

async def test_enforce_сейф_продолжает(monkeypatch):
    import services.enforcement as e

    await _журнал_на_sqlite(monkeypatch)
    assert await e.enforce_text_verdict(
        _Сессия(), _нарушитель(), {"blocked": False}, "Текст нарушает правила"
    ) is None


async def test_enforce_до_порога_422_со_счётом(monkeypatch):
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _страйк(фабрика, Журнал, "u1", "ad")

    with pytest.raises(HTTPException) as ошибка:
        await e.enforce_text_verdict(
            _Сессия(), _нарушитель(), {"blocked": True, "category": "ad"},
            "Текст нарушает правила",
        )
    assert ошибка.value.status_code == 422
    assert "Нарушение 1 из 3" in ошибка.value.detail


async def test_enforce_на_пороге_возвращает_403_баном(monkeypatch, тихий_бан):
    """Готовый JSONResponse, не исключение: HTTPException откатил бы бан."""
    import json as _json

    import services.enforcement as e
    from middleware.auth import BANNED_CODE

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    for _ in range(3):
        await _страйк(фабрика, Журнал, "u1", "ad")

    ответ = await e.enforce_text_verdict(
        _Сессия(), _нарушитель(), {"blocked": True, "category": "ad"},
        "Текст нарушает правила",
    )
    assert ответ is not None and ответ.status_code == 403
    тело = _json.loads(ответ.body)
    assert тело["code"] == BANNED_CODE
    assert тело["banned_until"], "срок обязан дойти до клиента — по нему экран бана"


# ── Фото-роутеры: страйк только за "ad" ───────────────────────────

@pytest.mark.parametrize(
    "путь",
    [
        "routers/upload.py",
        "routers/stories.py",
        # Кадры роликов и видео анкеты модерируются в общем сервисе —
        # ветка "ad" для них живёт там, а не в routers/reels.py
        "services/video_validation.py",
    ],
)
def test_фото_роутер_вешает_страйк_только_за_ad(путь):
    """Страховка от отката: ветка страйка стоит и отфильтрована по "ad".

    Полный интеграционный прогон требует R2 и гейта анкеты; сам механизм
    порога покрыт юнитами выше, здесь — что роутер его вообще зовёт и не
    зовёт для блокировок без категории (нудити не должна копить страйки).
    """
    текст = (_КОРЕНЬ / "api" / путь).read_text(encoding="utf-8")
    assert "enforce_text_verdict(" in текст
    assert 'get("category") == "ad"' in текст


# ── Контентные страйки (А2): снятый по жалобам контент ────────────

def _снятие(фабрика, Журнал, user_id, дней_назад=0.0):
    """Прошлое снятие в журнале — как его пишет register_content_strike."""
    return _страйк(
        фабрика, Журнал, user_id, "content",
        дней_назад=дней_назад, content_type="content_removed",
    )


class _СессияСАвтором(_Сессия):
    """register_content_strike грузит автора из сессии запроса по id."""

    def __init__(self, автор):
        self._автор = автор

    async def execute(self, *_a, **_kw):
        автор = self._автор

        class _Рез:
            def scalar_one_or_none(self):
                return автор

        return _Рез()


async def test_снятие_пишет_страйк_и_до_порога_не_банит(monkeypatch):
    from sqlalchemy import select

    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    автор = _нарушитель()
    await e.register_content_strike(_СессияСАвтором(автор), "u1", "reel:r1")

    async with фабрика() as session:
        записи = (await session.execute(select(Журнал))).scalars().all()
    assert len(записи) == 1
    assert (записи[0].content_type, записи[0].category, записи[0].result) == (
        "content_removed", "content", "blocked",
    )
    assert записи[0].content == "reel:r1", "метка — модератору нужно знать, что снято"
    assert автор.is_banned is False


async def test_третье_снятие_за_квартал_банит_лестницей(monkeypatch, тихий_бан):
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _снятие(фабрика, Журнал, "u1", дней_назад=80)
    await _снятие(фабрика, Журнал, "u1", дней_назад=10)

    автор = _нарушитель()
    await e.register_content_strike(_СессияСАвтором(автор), "u1", "story:s1")
    assert автор.is_banned is True
    # Первая ступень лестницы content (24ч), не вечный бан
    assert автор.banned_until is not None


async def test_снятия_вне_окна_не_двигают_лестницу(monkeypatch, тихий_бан):
    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    await _снятие(фабрика, Журнал, "u1", дней_назад=91)
    await _снятие(фабрика, Журнал, "u1", дней_назад=95)

    автор = _нарушитель()
    await e.register_content_strike(_СессияСАвтором(автор), "u1", "reel:r2")
    assert автор.is_banned is False


async def test_забаненному_автору_снятия_не_копятся(monkeypatch):
    """Пока автор отбывает срок, жалобы снимают его СТАРЫЙ контент — это не
    новые действия, и двигать лестницу они не должны. Запись тоже не пишем:
    после разбана хвост отсидки не превращается в готовый счёт."""
    from sqlalchemy import select

    import services.enforcement as e

    фабрика, Журнал = await _журнал_на_sqlite(monkeypatch)
    автор = _нарушитель(is_banned=True)
    await e.register_content_strike(_СессияСАвтором(автор), "u1", "reel:r3")

    async with фабрика() as session:
        записи = (await session.execute(select(Журнал))).scalars().all()
    assert записи == []


async def test_удалённый_автор_не_роняет_жалобу(monkeypatch):
    import services.enforcement as e

    await _журнал_на_sqlite(monkeypatch)
    # Автор успел удалить аккаунт — жалобщик всё равно получает свой 204
    assert await e.register_content_strike(_СессияСАвтором(None), "u1", "reel:r4") is None


@pytest.mark.parametrize(
    "путь, вхождений",
    [("routers/rooms.py", 1), ("routers/stories.py", 1), ("routers/reels.py", 2)],
)
def test_ручки_жалоб_вешают_контентный_страйк(путь, вхождений):
    """Страховка от отката: каждая точка снятия (ролик, история, сообщение
    комнаты, комментарий) зовёт register_content_strike."""
    текст = (_КОРЕНЬ / "api" / путь).read_text(encoding="utf-8")
    assert текст.count("register_content_strike(") == вхождений


# ── Паритет бот↔API ───────────────────────────────────────────────
#
# Бот живёт в отдельном venv (aiogram), импортировать его отсюда нельзя —
# константы читаются через ast: в bot/services/enforcement.py они объявлены
# сырыми литералами (штуки/часы) именно ради этой сверки.

def _бот_литерал(относительный: str, имя: str):
    дерево = ast.parse((_КОРЕНЬ / относительный).read_text(encoding="utf-8"))
    for узел in ast.walk(дерево):
        цели = []
        if isinstance(узел, ast.Assign):
            цели = узел.targets
        elif isinstance(узел, ast.AnnAssign) and узел.value is not None:
            цели = [узел.target]
        for цель in цели:
            if isinstance(цель, ast.Name) and цель.id == имя:
                return ast.literal_eval(узел.value)
    raise AssertionError(f"{имя} не найдено в {относительный}")


def test_паритет_категорий_и_правил_страйков():
    import services.ai_moderation as m
    import services.enforcement as e

    assert _бот_литерал("bot/services/moderation.py", "TEXT_CATEGORIES") == m.TEXT_CATEGORIES

    сырые = _бот_литерал("bot/services/enforcement.py", "TEXT_STRIKE_RULES_RAW")
    assert set(сырые) == set(e.TEXT_STRIKE_RULES)
    for категория, (порог, окно_часов) in сырые.items():
        api_порог, api_окно = e.TEXT_STRIKE_RULES[категория]
        assert (порог, timedelta(hours=окно_часов)) == (api_порог, api_окно), категория


def test_паритет_лестниц_и_причин():
    import services.enforcement as e

    лестницы = _бот_литерал("bot/services/enforcement.py", "BAN_LADDER_HOURS")
    # Бот банит только за текстовые категории; identity/reports/manual — в API
    assert set(лестницы) == set(e.TEXT_STRIKE_RULES)
    for категория, ступени in лестницы.items():
        api_ступени = e.BAN_LADDERS[категория]
        assert len(ступени) == len(api_ступени), категория
        for часы, api_срок in zip(ступени, api_ступени):
            assert (None if часы is None else timedelta(hours=часы)) == api_срок

    assert _бот_литерал("bot/services/enforcement.py", "TEXT_BAN_REASONS") == e.TEXT_BAN_REASONS


def test_паритет_амнистий_и_отзыва_токенов():
    import services.enforcement as e
    import services.token_revocation as tr
    from config import Settings

    бот = "bot/services/enforcement.py"
    assert tuple(_бот_литерал(бот, "AMNESTY_TYPES")) == e.AMNESTY_TYPES
    assert tuple(_бот_литерал(бот, "LADDER_AMNESTY_TYPES")) == e.LADDER_AMNESTY_TYPES
    assert _бот_литерал(бот, "BAN_APPLIED_TYPE") == e.BAN_APPLIED_TYPE
    assert timedelta(hours=_бот_литерал(бот, "BAN_HISTORY_HOURS")) == e.BAN_HISTORY_WINDOW

    assert _бот_литерал(бот, "REVOKED_BEFORE_KEY") == tr._USER_PREFIX
    # TTL отзыва сверяется с ДЕФОЛТОМ настройки, а не с env текущего стенда:
    # бот не читает апишный конфиг, и продовое значение — это дефолт
    assert _бот_литерал(бот, "REVOKE_TTL_HOURS") == (
        Settings.model_fields["JWT_ACCESS_EXPIRE_HOURS"].default
    )


def test_паритет_фото_промптов():
    """Оба канала просят у фото-модели категорию "ad" — реклама на снимке
    копит один и тот же счёт страйков, из какого канала ни пришла."""
    for путь in ("api/services/ai_moderation.py", "bot/services/moderation.py"):
        текст = (_КОРЕНЬ / путь).read_text(encoding="utf-8")
        assert '"category": "ad"/""' in текст, путь


def test_бот_нормализует_вердикты_как_api():
    """Нормализация бота — его же интерпретатором: фото-блок без категории
    не получает страйк-категорию, текстовый — падает в "text"."""
    итог = _в_боте(
        """
import json
from services.moderation import _normalize_image_verdict, _normalize_text_verdict

print(json.dumps({
    "фото_ад": _normalize_image_verdict({"blocked": True, "category": "ad"})["category"],
    "фото_без": _normalize_image_verdict({"blocked": True, "reason": "nudity"})["category"],
    "фото_чужая": _normalize_image_verdict({"blocked": True, "category": "text"})["category"],
    "фото_сейф": _normalize_image_verdict({"blocked": False, "category": "ad"})["category"],
    "текст_без": _normalize_text_verdict({"blocked": True})["category"],
    "текст_выдумка": _normalize_text_verdict({"blocked": True, "category": "чушь"})["category"],
}, ensure_ascii=False))
"""
    )
    assert итог == {
        "фото_ад": "ad", "фото_без": "", "фото_чужая": "", "фото_сейф": "",
        "текст_без": "text", "текст_выдумка": "text",
    }
