"""Платный гейт раздела Таро.

Карта дня бесплатна — это повод открыть приложение, а не товар. Три
развёрнутых расклада закрыты фичей `tarot_spreads`. Тариф подменяем прямо в
модуле роутера (`current_tier`), поэтому живая база здесь не нужна — проверяем
именно решение гейта, а не выборку подписки из БД.

Имя нужного уровня в проверках берём из тарифной линейки, а не пишем словом:
фича уже переезжала между уровнями, и зашитое имя пришлось бы искать по всем
тестам заново.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def клиент(app, monkeypatch):
    from database.connection import get_session
    from middleware.auth import get_current_user
    from models.models import User
    import routers.tarot as tarot_mod
    import services.ai_moderation as ai_moderation

    # Без ключа Zhipu интерпретация собирается из заготовок — в тесте не ходим
    # в сеть и не зависим от внешнего сервиса.
    monkeypatch.setattr(ai_moderation, "_get_zhipu_client", lambda: None)

    уровень = {"tier": "free"}

    async def _tier(_session, _user_id):
        return уровень["tier"]

    # Гейт зовёт current_tier из пространства имён роутера — его и подменяем.
    monkeypatch.setattr(tarot_mod, "current_tier", _tier)

    async def _sess():
        # current_tier подменён и сессию не трогает — отдаём заглушку.
        yield None

    юзер = User(id=str(uuid.uuid4()), telegram_id=1, role="user")

    async def _user():
        return юзер

    было = {
        get_session: app.dependency_overrides.get(get_session),
        get_current_user: app.dependency_overrides.get(get_current_user),
    }
    app.dependency_overrides[get_session] = _sess
    app.dependency_overrides[get_current_user] = _user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            c.тариф = lambda t: уровень.update(tier=t)  # type: ignore[attr-defined]
            yield c
    finally:
        # Возвращаем ровно то, что было: app — session-scoped, чужие
        # переопределения из соседних тестов затирать нельзя.
        for ключ, значение in было.items():
            if значение is None:
                app.dependency_overrides.pop(ключ, None)
            else:
                app.dependency_overrides[ключ] = значение


async def test_карта_дня_бесплатна(клиент):
    """Вход в раздел открыт даже на free — иначе карта дня не приманка."""
    клиент.тариф("free")
    r = await клиент.get("/api/tarot/day")
    assert r.status_code == 200, r.text
    assert r.json()["spread"] == "day"


async def test_карта_дня_сообщает_закрыты_ли_развороты(клиент):
    """Клиент узнаёт про замок из бесплатного ответа, а не пробой закрытого
    расклада.

    Проба стоила лишнего запроса и роняла экран: её ответ менял состояние,
    эффект перезапускался и грузил карту дня второй раз, а карточка успевала
    мигнуть скелетоном. Замерено было 2 запроса `/tarot/day` + 1 `/tarot/three`
    на одно открытие раздела.
    """
    from services.plans import FEATURE_MIN_TIER, TIERS

    клиент.тариф("free")
    тело = (await клиент.get("/api/tarot/day")).json()
    assert тело["spreads_open"] is False, (
        "на free развороты закрыты — карта дня обязана это сообщить"
    )
    assert тело["required_tier_name"] == TIERS[FEATURE_MIN_TIER["tarot_spreads"]].name

    клиент.тариф(FEATURE_MIN_TIER["tarot_spreads"])
    тело = (await клиент.get("/api/tarot/day")).json()
    assert тело["spreads_open"] is True, "на нужном уровне замка быть не должно"


async def test_бесплатному_развороты_закрыты(клиент):
    """Три развёрнутых расклада на free отдают 403 с именем нужного тарифа."""
    from services.plans import FEATURE_MIN_TIER, TIERS

    клиент.тариф("free")
    нужный = TIERS[FEATURE_MIN_TIER["tarot_spreads"]].name

    for путь in ("/api/tarot/three", "/api/tarot/relationship"):
        r = await клиент.get(путь)
        assert r.status_code == 403, f"{путь}: {r.text}"
        assert нужный in r.json()["detail"]

    # «Он и я» — тоже расклад: гейт срабатывает раньше валидации имён.
    r = await клиент.get(
        "/api/tarot/pair", params={"name_a": "Аня", "name_b": "Игорь"}
    )
    assert r.status_code == 403, r.text
    assert нужный in r.json()["detail"]


async def test_с_подпиской_развороты_открыты(клиент):
    """На нужном уровне расклад приходит целиком: карты и дисклеймер на месте."""
    from services.plans import FEATURE_MIN_TIER

    клиент.тариф(FEATURE_MIN_TIER["tarot_spreads"])
    r = await клиент.get("/api/tarot/three")
    assert r.status_code == 200, r.text

    тело = r.json()
    assert тело["spread"] == "three"
    assert len(тело["cards"]) == 3
    assert тело["disclaimer"]
